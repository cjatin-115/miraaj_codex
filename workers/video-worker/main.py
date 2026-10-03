"""Redis-backed local worker for Miraaj media analysis."""

import json
import logging
import os
import shutil
import sys
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

API_SOURCE = Path(__file__).resolve().parents[2] / "apps" / "api" / "src"
sys.path.insert(0, str(API_SOURCE))

from redis import Redis  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from miraaj_api.config import get_settings  # noqa: E402
from miraaj_api.database import SessionLocal  # noqa: E402
from miraaj_api.media_pipeline import MediaPipeline, analyze_audio  # noqa: E402
from miraaj_api.models import (  # noqa: E402
    Job,
    JobOutbox,
    Project,
    ProjectAnalysis,
    ProjectPlan,
    ProjectRender,
    ProjectAsset,
)  # noqa: E402
from miraaj_api.director import configured_director  # noqa: E402
from miraaj_api.timeline_builder import TimelineBuilder  # noqa: E402
from miraaj_api.media_tools import media_tool  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("miraaj.worker")
QUEUE = "miraaj:jobs"
PROCESSING = "miraaj:jobs:processing"


def process_render_job(
    redis_client: Redis,
    raw: bytes | str,
    payload: dict,
    session: Session,
    project: Project,
    job: Job,
) -> None:
    render = session.scalar(select(ProjectRender).where(ProjectRender.job_id == job.id))
    plan = session.get(ProjectPlan, project.id)
    if render is None or plan is None or plan.status != "ready" or not plan.timeline:
        raise RuntimeError("Render requires a ready, validated timeline.")
    if not Path(project.source_video_path).is_file():
        raise RuntimeError("The original uploaded recording is missing.")
    root = Path(__file__).resolve().parents[2]
    renderer_dir = root / "apps" / "renderer"
    public_media = renderer_dir / "public" / "media"
    public_media.mkdir(parents=True, exist_ok=True)
    source_copy = public_media / f"{render.id}{Path(project.source_video_path).suffix.lower()}"
    shutil.copy2(project.source_video_path, source_copy)
    assets = session.scalars(
        select(ProjectAsset).where(ProjectAsset.project_id == project.id)
    ).all()
    requested_assets = {
        str(scene.get("asset_request", {}).get("data", {}).get("asset_id"))
        for scene in plan.timeline.get("scenes", [])
        if scene.get("asset_request") and scene["asset_request"].get("data", {}).get("asset_id")
    }
    copied_assets: dict[str, Path] = {}
    for asset in assets:
        if asset.id in requested_assets:
            asset_path = Path(asset.path)
            if not asset_path.is_file():
                raise RuntimeError(f"Timeline asset {asset.id} is missing from local storage.")
            copied = public_media / f"asset-{asset.id}{asset_path.suffix.lower()}"
            shutil.copy2(asset_path, copied)
            copied_assets[asset.id] = copied
    work = Path(get_settings().storage_path) / ".render_work" / render.id
    work.mkdir(parents=True, exist_ok=True)
    output = get_settings().render_path / project.id / f"{render.id}.mp4"
    output.unlink(missing_ok=True)
    props_path, request_path = work / "props.json", work / "request.json"
    analysis = project.analysis
    transcript = analysis.transcript or {} if analysis else {}
    style_path = root / "packages" / "style-system" / "modern_creator_v1.json"
    import json as _json

    props_path.write_text(
        _json.dumps(
            {
                "timeline": plan.timeline,
                "sourceUrl": f"media/{source_copy.name}",
                "sourceHasAudio": bool((analysis.video_metadata or {}).get("has_audio"))
                if analysis
                else False,
                "assetUrls": {
                    asset_id: f"media/{path.name}" for asset_id, path in copied_assets.items()
                },
                "wordTimestamps": transcript.get("words", []),
                "volume": render.volume,
                "style": _json.loads(style_path.read_text(encoding="utf-8")),
            }
        ),
        encoding="utf-8",
    )
    request_path.write_text(
        _json.dumps({"input": str(props_path), "output": str(output), "profile": render.profile}),
        encoding="utf-8",
    )
    tsx = root / "node_modules" / "tsx" / "dist" / "cli.mjs"
    script = renderer_dir / "src" / "render.ts"
    if not tsx.is_file():
        raise RuntimeError(
            "Renderer dependencies are missing. Run npm install from the project root."
        )
    render.status, render.stage, render.progress = "processing", "processing", 0.02
    job.status = "running"
    session.commit()
    process = subprocess.Popen(
        [shutil.which("node") or "node", str(tsx), str(script), str(request_path)],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    error_event = None
    previous_status, previous_progress = render.status, render.progress
    try:
        assert process.stdout is not None
        for line in process.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.info("Renderer: %s", line.strip()[-600:])
                continue
            stage = event.get("event")
            if stage == "failed":
                error_event = event.get("error")
                continue
            if stage in {"rendering", "encoding"}:
                fraction = max(0.0, min(1.0, float(event.get("progress", 0)) / 100))
                render.status = stage
                render.stage = stage
                render.progress = round(0.05 + 0.88 * fraction, 4)
                if (
                    render.status != previous_status
                    or render.progress >= previous_progress + 0.02
                    or render.progress == 0.93
                ):
                    session.commit()
                    previous_status, previous_progress = render.status, render.progress
            elif stage == "bundling":
                render.status, render.stage = "processing", "processing"
                render.progress = round(0.01 + 0.04 * float(event.get("progress", 0)), 4)
                session.commit()
        code = process.wait()
    except Exception:
        process.kill()
        process.wait()
        raise
    finally:
        source_copy.unlink(missing_ok=True)
        for copied_asset in copied_assets.values():
            copied_asset.unlink(missing_ok=True)
        try:
            public_media.rmdir()
            (renderer_dir / "public").rmdir()
        except OSError:
            pass
    if code != 0 or error_event:
        raise RuntimeError(str(error_event or f"Remotion render exited with status {code}."))
    render.status, render.stage, render.progress = (
        "quality_check",
        "quality_check",
        0.96,
    )
    session.commit()
    metadata = validate_render(
        output,
        render.profile,
        float(plan.timeline["duration"]),
        bool((analysis.video_metadata or {}).get("has_audio")) if analysis else False,
        bool((analysis.video_analysis or {}).get("face_analysis", {}).get("detected_samples"))
        if analysis
        else False,
        plan.timeline,
        bool(
            analysis
            and float((analysis.audio_analysis or {}).get("speech_duration_seconds") or 0) > 0
        ),
        render.volume,
    )
    render.output_path = str(output)
    source_metadata = analysis.video_metadata or {} if analysis else {}
    render.source_width, render.source_height = (
        int(source_metadata.get("width") or 0),
        int(source_metadata.get("height") or 0),
    )
    render.output_width, render.output_height = (
        int(metadata["width"]),
        int(metadata["height"]),
    )
    render.status, render.stage, render.progress = "completed", "completed", 1
    job.status = "succeeded"
    session.commit()
    logger.info("Render complete for project %s: %s", project.id, output)


def validate_render(
    output: Path,
    profile: str,
    expected_duration: float,
    expect_audio: bool,
    expect_face: bool,
    timeline: dict,
    expect_speech: bool = False,
    volume: float = 1.0,
) -> dict:
    ffprobe, ffmpeg = media_tool("ffprobe"), media_tool("ffmpeg")
    if not ffprobe or not ffmpeg:
        raise RuntimeError("FFmpeg and FFprobe are required to validate a render.")
    if not output.is_file() or output.stat().st_size < 4096:
        raise RuntimeError("Remotion did not produce a usable MP4 file.")
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if probe.returncode:
        raise RuntimeError(f"FFprobe cannot open rendered MP4: {probe.stderr[-1000:]}")
    data = json.loads(probe.stdout)
    video = next(
        (stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"),
        None,
    )
    audio = audio_stream is not None
    dimensions = (1080, 1920) if profile == "vertical_1080" else (2160, 3840)
    if not video or (video.get("width"), video.get("height")) != dimensions:
        raise RuntimeError(
            f"Wrong output dimensions; expected {dimensions}, got {None if not video else (video.get('width'), video.get('height'))}."
        )
    if video.get("codec_name") != "h264":
        raise RuntimeError(f"Output video codec must be H.264; got {video.get('codec_name')}.")
    rate = video.get("avg_frame_rate", "0/1").split("/")
    fps = float(rate[0]) / max(1, float(rate[1]))
    if abs(fps - 30) > 0.02:
        raise RuntimeError(f"Output frame rate must be 30 fps; got {fps}.")
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    if abs(duration - expected_duration) > 0.12:
        raise RuntimeError(
            f"Output duration differs from timeline ({duration:.3f}s vs {expected_duration:.3f}s)."
        )
    if expect_audio and not audio:
        raise RuntimeError(
            "The uploaded source contains audio, but the rendered MP4 has no audio stream."
        )
    audio_metrics = None
    if audio_stream is not None:
        if audio_stream.get("codec_name") != "aac":
            raise RuntimeError(
                f"Output audio codec must be AAC; got {audio_stream.get('codec_name')}."
            )
        with tempfile.TemporaryDirectory(
            prefix=f".{output.stem}-audio-qc-", dir=output.parent
        ) as temp_dir:
            wav_path = Path(temp_dir) / "rendered-audio.wav"
            audio_decode = subprocess.run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-i",
                    str(output),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(wav_path),
                ],
                capture_output=True,
                text=True,
                timeout=max(60, expected_duration * 5),
                check=False,
            )
            if audio_decode.returncode or not wav_path.is_file():
                raise RuntimeError(
                    f"Could not decode rendered audio for quality checks: {audio_decode.stderr[-1000:]}"
                )
            audio_metrics = analyze_audio(wav_path)
        audio_duration = float(audio_metrics["duration_seconds"])
        if abs(audio_duration - expected_duration) > 0.15:
            raise RuntimeError(
                f"Rendered audio is out of sync with the timeline ({audio_duration:.3f}s vs {expected_duration:.3f}s)."
            )
        peak_dbfs = audio_metrics.get("peak_dbfs")
        if peak_dbfs is not None and float(peak_dbfs) >= -0.01:
            raise RuntimeError(f"Rendered audio clips at {peak_dbfs} dBFS.")
        if (
            expect_speech
            and volume > 0
            and float(audio_metrics.get("speech_duration_seconds") or 0) < 0.1
        ):
            raise RuntimeError(
                "The uploaded recording contains speech, but rendered audio is effectively silent."
            )
    decode = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(output),
            "-c:v",
            "rawvideo",
            "-f",
            "null",
            os.devnull,
        ],
        capture_output=True,
        text=True,
        timeout=max(60, expected_duration * 5),
        check=False,
    )
    if decode.returncode or decode.stderr.strip():
        raise RuntimeError(
            f"FFmpeg found corrupt or undecodable output frames: {decode.stderr[-1200:]}"
        )
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise RuntimeError(
            "OpenCV is required for decoded-frame and caption quality checks."
        ) from error
    capture = cv2.VideoCapture(str(output))
    if not capture.isOpened():
        raise RuntimeError("OpenCV could not open the rendered MP4.")
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    expected_frames = round(expected_duration * 30)
    if abs(frame_count - expected_frames) > 1:
        capture.release()
        raise RuntimeError(
            f"Output frame count does not match the 30 fps timeline ({frame_count} vs {expected_frames})."
        )
    near_black = 0
    for _ in range(frame_count):
        ok, frame = capture.read()
        if not ok:
            capture.release()
            raise RuntimeError("OpenCV encountered a corrupt or missing frame in the rendered MP4.")
        luminance = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if float(np.mean(luminance)) < 1.5 and float(np.mean(luminance < 6)) > 0.998:
            near_black += 1
    caption_samples = 0
    visible_caption_samples = 0
    for scene in timeline.get("scenes", []):
        if scene.get("type") != "caption" or not scene.get("text", "").strip():
            continue
        caption_samples += 1
        capture.set(
            cv2.CAP_PROP_POS_MSEC,
            (float(scene["start"]) + float(scene["duration"]) / 2) * 1000,
        )
        ok, frame = capture.read()
        if not ok:
            capture.release()
            raise RuntimeError(f"Could not inspect rendered caption scene {scene.get('id')}.")
        scale = frame.shape[0] / 1920
        roi = frame[
            int(0.76 * frame.shape[0]) : int(0.96 * frame.shape[0]),
            int(0.05 * frame.shape[1]) : int(0.95 * frame.shape[1]),
        ]
        bright = (np.max(roi, axis=2) > 188) & (np.min(roi, axis=2) > 110)
        if int(np.count_nonzero(bright)) >= max(15, int(25 * scale)):
            visible_caption_samples += 1
    capture.release()
    if near_black:
        raise RuntimeError(f"Quality check found {near_black} fully black/dropped frames.")
    if caption_samples and visible_caption_samples < max(1, int(caption_samples * 0.75)):
        raise RuntimeError(
            "The lower caption safe area did not contain visible caption pixels in enough sampled scenes."
        )
    if expect_face:
        capture = cv2.VideoCapture(str(output))
        cascade = cv2.CascadeClassifier(
            str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        )
        found = False
        for second in range(0, max(1, int(expected_duration)), 2):
            capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
            ok, frame = capture.read()
            if ok and len(
                cascade.detectMultiScale(
                    cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.1, 4, minSize=(48, 48)
                )
            ):
                found = True
                break
        capture.release()
        if not found:
            raise RuntimeError(
                "Face analysis detected the speaker in the source, but QA could not find the speaker in rendered frames."
            )
    video_bitrate = int(video.get("bit_rate") or data.get("format", {}).get("bit_rate") or 0)
    if video_bitrate <= 0:
        raise RuntimeError("FFprobe could not verify a positive video bitrate.")
    return {
        "width": video["width"],
        "height": video["height"],
        "fps": fps,
        "duration": duration,
        "audio": audio,
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
        "audio_duration": audio_metrics["duration_seconds"] if audio_metrics else None,
        "audio_loudness_dbfs": audio_metrics["loudness_dbfs"] if audio_metrics else None,
        "audio_peak_dbfs": audio_metrics["peak_dbfs"] if audio_metrics else None,
        "video_codec": video.get("codec_name"),
        "video_bitrate": video_bitrate,
        "frame_count": frame_count,
        "black_frames": near_black,
        "caption_samples": caption_samples,
        "visible_caption_samples": visible_caption_samples,
    }


def dispatch_queued_jobs(redis_client: Redis, batch_size: int = 50) -> int:
    session: Session = SessionLocal()
    try:
        pending = session.scalars(
            select(JobOutbox)
            .where(JobOutbox.dispatched_at.is_(None))
            .order_by(JobOutbox.created_at)
            .limit(batch_size)
        ).all()
        count = 0
        for outbox in pending:
            job = session.get(Job, outbox.job_id)
            if job is None or job.status != "queued":
                outbox.dispatched_at = datetime.now(timezone.utc)
                continue
            project = session.get(Project, job.project_id)
            if project is None:
                outbox.dispatched_at = datetime.now(timezone.utc)
                continue
            redis_client.rpush(
                QUEUE,
                json.dumps({"id": job.id, "project_id": project.id, "kind": job.kind}),
            )
            outbox.dispatched_at = datetime.now(timezone.utc)
            count += 1
        session.commit()
        return count
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def recover_interrupted_jobs() -> int:
    """Return jobs left running by a killed worker to a retryable state."""
    session: Session = SessionLocal()
    try:
        jobs = session.scalars(select(Job).where(Job.status == "running")).all()
        for job in jobs:
            job.status = "queued"
            if job.kind == "render":
                render = session.scalar(select(ProjectRender).where(ProjectRender.job_id == job.id))
                if render is not None:
                    render.status, render.stage, render.progress, render.error = (
                        "queued",
                        "queued",
                        0,
                        None,
                    )
            elif job.kind == "director":
                plan = session.get(ProjectPlan, job.project_id)
                if plan is not None and plan.status == "planning":
                    plan.status = "queued"
            else:
                project = session.get(Project, job.project_id)
                if project and project.analysis:
                    project.analysis.status, project.status = "queued", "created"
        session.commit()
        return len(jobs)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def update_job(
    redis_client: Redis, raw: bytes | str, payload: dict, pipeline: MediaPipeline
) -> None:
    session: Session = SessionLocal()
    try:
        job = session.get(Job, payload["id"])
        project = session.get(Project, payload["project_id"])
        if job is None or project is None:
            logger.error("Ignoring queued job with missing project records: %s", payload)
            return
        if job.status not in {"queued", "running"}:
            logger.info("Skipping already claimed job %s (status=%s)", job.id, job.status)
            return
        if job.kind == "render":
            process_render_job(redis_client, raw, payload, session, project, job)
            return
        if job.kind == "director":
            plan_record = session.get(ProjectPlan, project.id)
            if (
                plan_record is None
                or project.analysis is None
                or project.analysis.status != "ready"
            ):
                raise RuntimeError(
                    "Director job requires completed media analysis and a plan record."
                )
            job.status, plan_record.status = "running", "planning"
            session.commit()
            analysis = project.analysis
            context = {
                "script": project.script_text,
                "transcript": analysis.transcript or {},
                "word_timestamps": (analysis.transcript or {}).get("words", []),
                "video_metadata": analysis.video_metadata or {},
                "face_framing_analysis": analysis.video_analysis or {},
                "audio_analysis": analysis.audio_analysis or {},
                "target_duration": analysis.target_duration,
                "style_profile": "modern_creator_v1",
                "available_scene_components": [
                    "captions",
                    "talking_head",
                    "keyword_text",
                    "statistics",
                    "comparison",
                    "graph",
                    "quote",
                    "cta",
                ],
            }
            project_assets = session.scalars(
                select(ProjectAsset).where(ProjectAsset.project_id == project.id)
            ).all()
            context["available_assets"] = [
                {"id": asset.id, "kind": asset.kind, "metadata": asset.asset_metadata}
                for asset in project_assets
            ]
            edit_plan = configured_director().create_plan(context)
            metadata = analysis.video_metadata or {}
            faces = (analysis.video_analysis or {}).get("face_analysis", {}).get("samples", [])
            style_path = (
                Path(__file__).resolve().parents[2]
                / "packages"
                / "style-system"
                / "modern_creator_v1.json"
            )
            import json as _json

            style = _json.loads(style_path.read_text(encoding="utf-8"))
            available_assets = {
                asset.id: {"kind": asset.kind, "metadata": asset.asset_metadata}
                for asset in project_assets
            }
            timeline = TimelineBuilder().build(
                edit_plan,
                float(metadata.get("duration_seconds") or 0),
                style,
                faces,
                available_assets,
            )
            plan_record.edit_plan, plan_record.timeline = edit_plan, timeline
            plan_record.status, plan_record.error = "ready", None
            job.status = "succeeded"
            session.commit()
            logger.info("Director plan ready for project %s", project.id)
            return
        if project.analysis is None:
            raise RuntimeError("Media analysis record is missing.")
        analysis: ProjectAnalysis = project.analysis
        job.status = "running"
        project.status = "analyzing"
        analysis.status = "analyzing"
        session.commit()
        logger.info("Analyzing project %s", project.id)

        result = pipeline.process(project.id, Path(project.source_video_path))
        analysis.content_hash = result["content_hash"]
        analysis.video_metadata = result["video_metadata"]
        analysis.video_analysis = result["video_analysis"]
        analysis.audio_analysis = result["audio_analysis"]
        analysis.transcript = result["transcript"]
        analysis.status = "ready"
        analysis.error = None
        project.status = "ready"
        job.status = "succeeded"
        session.commit()
        logger.info(
            "Analysis ready for project %s; cache_hit=%s",
            project.id,
            result["cache_hit"],
        )
    except Exception as error:
        session.rollback()
        logger.exception("Media analysis failed for %s", payload.get("project_id"))
        project = session.get(Project, payload.get("project_id", ""))
        if project is not None:
            job = session.get(Job, payload.get("id", ""))
            if job is not None and job.kind == "director":
                plan_record = session.get(ProjectPlan, project.id)
                if plan_record is not None:
                    plan_record.status, plan_record.error = "failed", str(error)[:2000]
                if job is not None:
                    job.status = "failed"
            elif job is not None and job.kind == "render":
                render = session.scalar(select(ProjectRender).where(ProjectRender.job_id == job.id))
                if render is not None:
                    render.status, render.stage, render.error = (
                        "failed",
                        "failed",
                        str(error)[:2000],
                    )
                job.status = "failed"
            else:
                project.status = "failed"
            if project.analysis is not None and (job is None or job.kind != "director"):
                project.analysis.status = "failed"
                project.analysis.error = str(error)[:2000]
            if job is not None:
                job.status = "failed"
            session.commit()
    finally:
        session.close()
        redis_client.lrem(PROCESSING, 1, raw)


def run() -> None:
    settings = get_settings()
    recover_interrupted_jobs()
    media_pipeline = MediaPipeline(
        settings.storage_path,
        ffmpeg=media_tool("ffmpeg"),
        ffprobe=media_tool("ffprobe"),
        whisper_model=settings.whisper_model_size,
    )
    with Redis.from_url(settings.redis_url, decode_responses=True) as redis_client:
        redis_client.ping()
        # Requeue work left in the processing list after a worker crash.
        while redis_client.rpoplpush(PROCESSING, QUEUE):
            pass
        logger.info("Miraaj video worker listening on %s", QUEUE)
        while True:
            try:
                dispatch_queued_jobs(redis_client)
                item = redis_client.blmove(QUEUE, PROCESSING, timeout=3, src="LEFT", dest="RIGHT")
                if item is None:
                    continue
                payload = json.loads(item)
                update_job(redis_client, item, payload, media_pipeline)
            except KeyboardInterrupt:
                logger.info("Worker stopping")
                return
            except Exception:
                logger.exception("Worker loop error; retrying shortly")
                time.sleep(2)


if __name__ == "__main__":
    run()
