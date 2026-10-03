import json
import hashlib
import logging
import math
import shutil
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from miraaj_api.providers import TranscriptionProvider

logger = logging.getLogger("miraaj.media")


class MediaProcessingError(RuntimeError):
    pass


def _run(args: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MediaProcessingError(f"Could not run {Path(args[0]).name}: {error}") from error
    if result.returncode:
        details = (result.stderr or result.stdout or "Unknown media tool error").strip()
        raise MediaProcessingError(details[-1600:])
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_video(path: Path, ffprobe: str | None = None) -> dict:
    executable = ffprobe or shutil.which("ffprobe")
    if not executable:
        raise MediaProcessingError(
            "FFprobe is required for video analysis. Install FFmpeg and add it to PATH."
        )
    result = _run(
        [executable, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        timeout=30,
    )
    try:
        data = json.loads(result.stdout)
        video = next(
            stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"
        )
    except (json.JSONDecodeError, StopIteration) as error:
        raise MediaProcessingError("The uploaded file is not a readable video.") from error
    duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise MediaProcessingError("The video has no usable duration.")
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
    try:
        numerator, denominator = (int(part) for part in rate.split("/", 1))
        fps = numerator / denominator if denominator else 0
    except (ValueError, ZeroDivisionError):
        fps = 0
    audio_streams = [
        stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"
    ]
    format_data = data.get("format", {})
    return {
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": round(fps, 3),
        "duration_seconds": round(duration, 3),
        "video_codec": video.get("codec_name"),
        "bitrate": int(format_data.get("bit_rate") or video.get("bit_rate") or 0),
        "has_audio": bool(audio_streams),
        "audio_streams": [
            {
                "codec": item.get("codec_name"),
                "sample_rate": item.get("sample_rate"),
                "channels": item.get("channels"),
            }
            for item in audio_streams
        ],
    }


def analyze_audio(wav_path: Path, *, silence_threshold_db: float = -42.0) -> dict:
    with wave.open(str(wav_path), "rb") as audio:
        rate, channels, sample_width, count = (
            audio.getframerate(),
            audio.getnchannels(),
            audio.getsampwidth(),
            audio.getnframes(),
        )
        raw = audio.readframes(count)
    if count == 0:
        return {
            "audio_present": False,
            "duration_seconds": 0,
            "silence_regions": [],
            "speech_duration_seconds": 0,
            "loudness_dbfs": None,
            "peak_dbfs": None,
            "speaking_rate_wpm": None,
        }
    import numpy as np

    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(sample_width)
    if dtype is None:
        raise MediaProcessingError(f"Unsupported WAV sample width: {sample_width} bytes")
    samples = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    scale = float(1 << (sample_width * 8 - 1))
    normalized = samples / scale
    duration = count / rate
    frame_size = max(1, rate // 4)
    silent_ranges = []
    active_seconds = 0.0
    run_start = None
    for index in range(0, len(normalized), frame_size):
        frame = normalized[index : index + frame_size]
        if not len(frame):
            continue
        rms = float(np.sqrt(np.mean(frame * frame)))
        db = 20 * math.log10(max(rms, 1e-8))
        start, end = index / rate, min(duration, (index + len(frame)) / rate)
        if db > silence_threshold_db:
            active_seconds += end - start
            if run_start is not None:
                silent_ranges.append({"start": round(run_start, 2), "end": round(start, 2)})
                run_start = None
        elif run_start is None:
            run_start = start
    if run_start is not None:
        silent_ranges.append({"start": round(run_start, 2), "end": round(duration, 2)})
    rms = float(np.sqrt(np.mean(normalized * normalized))) if len(normalized) else 0
    peak = float(np.max(np.abs(normalized))) if len(normalized) else 0
    return {
        "audio_present": peak > 0,
        "duration_seconds": round(duration, 3),
        "speech_duration_seconds": round(active_seconds, 3),
        "silence_regions": silent_ranges,
        "loudness_dbfs": round(20 * math.log10(max(rms, 1e-8)), 2),
        "peak_dbfs": round(20 * math.log10(max(peak, 1e-8)), 2),
        "sample_rate": rate,
        "speaking_rate_wpm": None,
    }


def _silence_segments(duration: float, silence_regions: list[dict]) -> list[dict]:
    usable = []
    cursor = 0.0
    for silence in silence_regions:
        start, end = max(cursor, float(silence["start"])), min(duration, float(silence["end"]))
        if start - cursor >= 1.0:
            usable.append({"start": round(cursor, 2), "end": round(start, 2)})
        cursor = max(cursor, end)
    if duration - cursor >= 1.0:
        usable.append({"start": round(cursor, 2), "end": round(duration, 2)})
    return usable or ([{"start": 0.0, "end": round(duration, 2)}] if duration > 0 else [])


def analyze_frames(frame_paths: list[Path], duration: float, silence_regions: list[dict]) -> dict:
    import cv2

    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path))
    samples = []
    centers = []
    histograms = []
    for frame_path in frame_paths:
        image = cv2.imread(str(frame_path))
        if image is None:
            continue
        height, width = image.shape[:2]
        faces = detector.detectMultiScale(
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 1.1, 4, minSize=(32, 32)
        )
        face = max(faces, key=lambda item: item[2] * item[3]) if len(faces) else None
        if face is not None:
            x, y, w, h = (int(value) for value in face)
            box = {
                "x": round(x / width, 4),
                "y": round(y / height, 4),
                "width": round(w / width, 4),
                "height": round(h / height, 4),
            }
            centers.append((box["x"] + box["width"] / 2, box["y"] + box["height"] / 2))
        else:
            box = None
        histograms.append(cv2.calcHist([image], [0], None, [32], [0, 256]))
        samples.append(
            {
                "frame": frame_path.name,
                "time": round(duration * (len(samples) + 0.5) / max(1, len(frame_paths)), 3),
                "face_bbox": box,
            }
        )
    histogram_deltas = [
        float(cv2.compareHist(histograms[i - 1], histograms[i], cv2.HISTCMP_BHATTACHARYYA))
        for i in range(1, len(histograms))
    ]
    scene_changes = [
        round(duration * (i + 1) / max(1, len(histograms)), 2)
        for i, delta in enumerate(histogram_deltas)
        if delta > 0.55
    ]
    face_boxes = [sample["face_bbox"] for sample in samples if sample["face_bbox"]]
    if centers:
        center_x = sum(point[0] for point in centers) / len(centers)
        center_y = sum(point[1] for point in centers) / len(centers)
        framing = (
            "centered" if abs(center_x - 0.5) < 0.14 else ("left" if center_x < 0.5 else "right")
        )
        movement = sum(math.dist(centers[i - 1], centers[i]) for i in range(1, len(centers))) / max(
            1, len(centers) - 1
        )
        stability = (
            "stable" if movement < 0.035 else ("slight_movement" if movement < 0.09 else "moving")
        )
        framing_type = (
            "close"
            if sum(box["height"] for box in face_boxes) / len(face_boxes) > 0.42
            else "medium_or_wide"
        )
        face_summary = {
            "detected_samples": len(face_boxes),
            "total_samples": len(samples),
            "average_position": {"x": round(center_x, 3), "y": round(center_y, 3)},
            "framing": framing,
            "approximate_framing": framing_type,
            "movement_per_sample": round(movement, 4),
            "camera_stability": stability,
            "samples": samples,
        }
    else:
        face_summary = {
            "detected_samples": 0,
            "total_samples": len(samples),
            "framing": "unknown",
            "approximate_framing": "unknown",
            "camera_stability": "unknown",
            "samples": samples,
        }
    return {
        "face_analysis": face_summary,
        "scene_change_times": scene_changes,
        "usable_segments": _silence_segments(duration, silence_regions),
        "analysis_method": "OpenCV Haar face detection and sampled-frame histogram changes",
    }


class LocalFasterWhisperTranscriptionProvider:
    """Offline word-timestamp transcription, loaded only when audio is present."""

    def __init__(self, model_size: str, model_path: Path):
        self.model_size = model_size
        self.model_path = model_path
        self._model = None

    def transcribe(self, audio_path: Path) -> dict:
        try:
            from faster_whisper import WhisperModel

            if self._model is None:
                self._model = WhisperModel(
                    self.model_size,
                    device="cpu",
                    compute_type="int8",
                    download_root=str(self.model_path),
                )
            segments, info = self._model.transcribe(
                str(audio_path), word_timestamps=True, vad_filter=True
            )
            words = []
            segment_records = []
            for segment in segments:
                segment_records.append(
                    {
                        "start": round(segment.start, 3),
                        "end": round(segment.end, 3),
                        "text": segment.text.strip(),
                    }
                )
                if segment.words:
                    for word in segment.words:
                        if word.start is None or word.end is None:
                            continue
                        probability = (
                            float(word.probability) if word.probability is not None else None
                        )
                        words.append(
                            {
                                "word": word.word.strip(),
                                "start": round(word.start, 3),
                                "end": round(word.end, 3),
                                "confidence": round(probability, 4)
                                if probability is not None
                                else None,
                            }
                        )
            probability = (
                float(info.language_probability) if info.language_probability is not None else None
            )
            return {
                "status": "complete",
                "language": info.language,
                "language_probability": round(probability, 3) if probability is not None else None,
                "segments": segment_records,
                "words": words,
            }
        except Exception as error:
            logger.exception("Local transcription failed")
            return {
                "status": "failed",
                "error": f"Local transcription failed: {error}",
                "words": [],
            }


class MediaPipeline:
    def __init__(
        self,
        storage_root: Path,
        *,
        ffmpeg: str | None = None,
        ffprobe: str | None = None,
        whisper_model: str = "base",
        transcription_provider: TranscriptionProvider | None = None,
    ):
        self.storage_root = storage_root
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg")
        self.ffprobe = ffprobe or shutil.which("ffprobe")
        self.whisper_model = whisper_model
        self.transcription_provider = (
            transcription_provider
            or LocalFasterWhisperTranscriptionProvider(whisper_model, storage_root / ".models")
        )

    def process(self, project_id: str, source_path: Path) -> dict:
        if not source_path.is_file():
            raise MediaProcessingError("The original video file is missing.")
        project_dir = source_path.parent
        digest = sha256_file(source_path)
        cache_dir = self.storage_root / ".cache" / digest
        manifest = cache_dir / "analysis.json"
        if manifest.is_file():
            cached = json.loads(manifest.read_text(encoding="utf-8"))
            original_project_id = cached.get("project_id", "")
            cached_artifacts = cached.get("artifacts", [])
            cache_complete = bool(cached_artifacts) and all(
                (cache_dir / name).exists() for name in cached_artifacts
            )
            if cache_complete:
                for name in cached_artifacts:
                    source = cache_dir / name
                    destination_name = name.replace(original_project_id, project_id, 1)
                    if source.is_dir():
                        shutil.copytree(source, project_dir / destination_name, dirs_exist_ok=True)
                    else:
                        shutil.copy2(source, project_dir / destination_name)
                cached["cache_hit"] = True
                cached["project_id"] = project_id
                cached["artifacts"] = [
                    name.replace(original_project_id, project_id, 1) for name in cached_artifacts
                ]
                cached["content_hash"] = digest
                transcript = cached.get("transcript") or {}
                if transcript.get("status") == "failed" and cached.get("video_metadata", {}).get(
                    "has_audio"
                ):
                    audio_path = project_dir / f"{project_id}_audio.wav"
                    if audio_path.is_file():
                        retry = self._transcribe(audio_path)
                        cached["transcript"] = retry
                        words = len(retry.get("words", []))
                        audio = cached.get("audio_analysis") or {}
                        audio["speaking_rate_wpm"] = (
                            round(
                                words
                                / max(float(audio.get("speech_duration_seconds") or 0), 0.1)
                                * 60,
                                1,
                            )
                            if words
                            else None
                        )
                        cached["audio_analysis"] = audio
                        if retry.get("status") == "complete":
                            cache_manifest = dict(
                                cached,
                                project_id=original_project_id,
                                artifacts=[
                                    name.replace(project_id, original_project_id, 1)
                                    for name in cached["artifacts"]
                                ],
                                cache_hit=False,
                            )
                            manifest.write_text(
                                json.dumps(cache_manifest, ensure_ascii=False), encoding="utf-8"
                            )
                return cached

        if not self.ffmpeg or not self.ffprobe:
            missing = ", ".join(
                name
                for name, value in (("FFmpeg", self.ffmpeg), ("FFprobe", self.ffprobe))
                if not value
            )
            raise MediaProcessingError(
                f"{missing} must be installed and available on PATH before analysis."
            )

        metadata = probe_video(source_path, self.ffprobe)
        proxy_name = f"{project_id}_analysis_proxy.mp4"
        audio_name = f"{project_id}_audio.wav"
        frames_dir_name = f"{project_id}_frames"
        proxy_path, audio_path = project_dir / proxy_name, project_dir / audio_name
        frames_dir = project_dir / frames_dir_name
        frames_dir.mkdir(parents=True, exist_ok=True)
        for stale_frame in frames_dir.glob("frame_*.jpg"):
            stale_frame.unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)
        proxy_args = [
            self.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-vf",
            "scale='min(720,iw)':-2",
            "-r",
            "24",
            "-fps_mode",
            "cfr",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            str(proxy_path),
        ]
        frame_count = max(1, min(24, math.ceil(metadata["duration_seconds"] / 5)))
        frame_jobs: list[tuple[Path, list[str]]] = []
        for index in range(frame_count):
            timestamp = min(
                metadata["duration_seconds"] - 0.001,
                metadata["duration_seconds"] * (index + 0.5) / frame_count,
            )
            frame_path = frames_dir / f"frame_{index + 1:03d}.jpg"
            frame_jobs.append(
                (
                    frame_path,
                    [
                        self.ffmpeg,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-ss",
                        f"{timestamp:.6f}",
                        "-i",
                        str(source_path),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=480:-2",
                        str(frame_path),
                    ],
                )
            )
        audio_args = None
        if metadata["has_audio"]:
            audio_args = [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source_path),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(audio_path),
            ]
        # Proxy, representative frames, and audio extraction read the same
        # immutable upload and can safely run concurrently. Limit fan-out to
        # four FFmpeg processes to keep the local worker responsive.
        with ThreadPoolExecutor(max_workers=min(4, frame_count + 2)) as executor:
            proxy_future = executor.submit(_run, proxy_args)
            frame_futures = [executor.submit(_run, args, timeout=60) for _, args in frame_jobs]
            audio_future = executor.submit(_run, audio_args) if audio_args else None
            proxy_future.result()
            for future in frame_futures:
                future.result()
            if audio_future:
                audio_future.result()
        frame_paths = sorted(frames_dir.glob("frame_*.jpg"))
        if not frame_paths:
            raise MediaProcessingError("FFmpeg did not extract any representative frames.")
        if metadata["has_audio"]:
            # Audio statistics and local transcription are independent reads of
            # the extracted PCM and can run while the video frames are analyzed.
            with ThreadPoolExecutor(max_workers=2) as executor:
                audio_future = executor.submit(analyze_audio, audio_path)
                transcript_future = executor.submit(self._transcribe, audio_path)
                audio = audio_future.result()
                video = analyze_frames(
                    frame_paths, metadata["duration_seconds"], audio.get("silence_regions", [])
                )
                transcript = transcript_future.result()
            spoken_words = len(transcript.get("words", []))
            audio["speaking_rate_wpm"] = (
                round(spoken_words / max(audio["speech_duration_seconds"], 0.1) * 60, 1)
                if spoken_words
                else None
            )
        else:
            audio = {
                "audio_present": False,
                "duration_seconds": metadata["duration_seconds"],
                "speech_duration_seconds": 0,
                "silence_regions": [],
                "loudness_dbfs": None,
                "peak_dbfs": None,
                "speaking_rate_wpm": None,
            }
            transcript = {"status": "skipped", "reason": "No audio stream was found.", "words": []}
            video = analyze_frames(
                frame_paths, metadata["duration_seconds"], audio.get("silence_regions", [])
            )
        result = {
            "project_id": project_id,
            "content_hash": digest,
            "cache_hit": False,
            "video_metadata": metadata,
            "video_analysis": video,
            "audio_analysis": audio,
            "transcript": transcript,
            "artifacts": [proxy_name, audio_name if audio_path.exists() else "", frames_dir_name],
        }
        result["artifacts"] = [name for name in result["artifacts"] if name]
        cache_dir.mkdir(parents=True, exist_ok=True)
        for name in result["artifacts"]:
            source = project_dir / name
            if source.is_dir():
                shutil.copytree(source, cache_dir / name, dirs_exist_ok=True)
            else:
                shutil.copy2(source, cache_dir / name)
        manifest.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result

    def _transcribe(self, audio_path: Path) -> dict:
        return self.transcription_provider.transcribe(audio_path)
