import shutil
import subprocess
import wave
from array import array
from pathlib import Path

import pytest

from miraaj_api.media_pipeline import (
    MediaPipeline,
    MediaProcessingError,
    analyze_audio,
    probe_video,
)
from miraaj_api.script_analysis import (
    ScriptAnalyzer,
    analyze_script_cached,
    assess_duration_target,
    estimate_duration,
)


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
MEDIA_TOOLS_AVAILABLE = bool(FFMPEG and FFPROBE)


def make_real_video(path: Path, duration: float, *, audio: bool = False) -> None:
    command = [
        FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=navy:s=320x240:r=12:d={duration}",
    ]
    if audio:
        command += [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-shortest",
            "-c:a",
            "aac",
        ]
    command += ["-c:v", "mpeg4", str(path)]
    subprocess.run(command, check=True, capture_output=True, text=True)


def test_empty_script_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        ScriptAnalyzer().analyze("  \n ")


def test_script_analysis_is_cached_by_content_hash(tmp_path: Path) -> None:
    first = analyze_script_cached("A compact script.", tmp_path)
    cached_file = next((tmp_path / "scripts").glob("*.json"))
    original = cached_file.read_bytes()
    second = analyze_script_cached("A compact script.", tmp_path)
    assert second == first
    assert cached_file.read_bytes() == original


def test_short_script_returns_word_sentence_and_duration_statistics() -> None:
    result = ScriptAnalyzer().analyze("Imagine a simpler camera. It can help today!")
    assert result["word_count"] == 8
    assert result["sentence_count"] == 2
    assert result["paragraph_count"] == 1
    assert result["likely_hooks"] == ["Imagine a simpler camera."]
    estimate = estimate_duration(result)
    assert (
        1
        <= estimate["estimated_min_duration"]
        <= estimate["recommended_duration"]
        <= estimate["estimated_max_duration"]
    )
    assert 0 < estimate["confidence"] <= 1


def test_long_script_duration_grows_with_word_count_and_target_warns() -> None:
    short = ScriptAnalyzer().analyze("A clear story.")
    long = ScriptAnalyzer().analyze(
        "A clear story with several concrete details and examples. " * 80
    )
    short_estimate, long_estimate = estimate_duration(short), estimate_duration(long)
    assert long_estimate["recommended_duration"] > short_estimate["recommended_duration"]
    fit = assess_duration_target({"estimated_min_duration": 35, "estimated_max_duration": 40}, 70)
    assert fit["status"] == "script_shorter_than_target"
    assert "adding content" in fit["message"]
    assert fit["script_expansion_available"] is False


def test_audio_analysis_finds_silence_and_levels(tmp_path: Path) -> None:
    wav_path = tmp_path / "tone.wav"
    samples = array("h", [8000] * 8000 + [0] * 8000)
    with wave.open(str(wav_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(samples.tobytes())
    result = analyze_audio(wav_path)
    assert result["duration_seconds"] == 2.0
    assert result["audio_present"] is True
    assert result["silence_regions"]
    assert result["peak_dbfs"] < 0


def test_opencv_frame_analysis_returns_framing_and_segments(tmp_path: Path) -> None:
    import cv2
    import numpy as np

    first, second = tmp_path / "frame_000.jpg", tmp_path / "frame_001.jpg"
    cv2.imwrite(str(first), np.zeros((240, 320, 3), dtype=np.uint8))
    cv2.imwrite(str(second), np.full((240, 320, 3), 255, dtype=np.uint8))
    from miraaj_api.media_pipeline import analyze_frames

    result = analyze_frames([first, second], 10, [{"start": 4, "end": 5}])
    assert result["face_analysis"]["total_samples"] == 2
    assert result["face_analysis"]["camera_stability"] == "unknown"
    assert result["scene_change_times"]
    assert result["usable_segments"] == [{"start": 0.0, "end": 4.0}, {"start": 5.0, "end": 10}]


@pytest.mark.skipif(
    not MEDIA_TOOLS_AVAILABLE,
    reason="Real FFmpeg and FFprobe binaries are required for this integration test.",
)
def test_real_media_ingestion_silent_clip_metadata_and_cache(tmp_path: Path) -> None:
    source = tmp_path / "silent.mp4"
    make_real_video(source, 3.0)
    metadata = probe_video(source, FFPROBE)
    assert metadata["has_audio"] is False
    assert metadata["video_codec"]
    assert metadata["width"] == 320
    assert 2.9 <= metadata["duration_seconds"] <= 3.1

    pipeline = MediaPipeline(tmp_path, ffmpeg=FFMPEG, ffprobe=FFPROBE)
    first = pipeline.process("first_project", source)
    second = pipeline.process("second_project", source)
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["transcript"]["status"] == "skipped"
    assert (tmp_path / "second_project_analysis_proxy.mp4").is_file()
    assert list((tmp_path / "second_project_frames").glob("frame_*.jpg"))


@pytest.mark.skipif(
    not MEDIA_TOOLS_AVAILABLE,
    reason="Real FFmpeg and FFprobe binaries are required for this integration test.",
)
def test_real_probe_handles_audio_short_long_invalid_and_corrupted_video(tmp_path: Path) -> None:
    with_audio = tmp_path / "with_audio.mp4"
    short = tmp_path / "short.mp4"
    long = tmp_path / "long.mp4"
    make_real_video(with_audio, 2.0, audio=True)
    make_real_video(short, 0.5)
    make_real_video(long, 12.0)
    assert probe_video(with_audio, FFPROBE)["has_audio"] is True
    assert probe_video(short, FFPROBE)["duration_seconds"] < 1
    assert probe_video(long, FFPROBE)["duration_seconds"] >= 12

    invalid = tmp_path / "not-video.mp4"
    invalid.write_text("not a movie", encoding="utf-8")
    with pytest.raises(MediaProcessingError):
        probe_video(invalid, FFPROBE)
    with pytest.raises(MediaProcessingError):
        probe_video(tmp_path / "missing.mp4", FFPROBE)
