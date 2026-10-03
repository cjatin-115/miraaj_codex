import logging
from pathlib import Path
import subprocess
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from miraaj_api.config import get_settings
from miraaj_api.database import Base, engine, get_db
from miraaj_api.models import (
    Job,
    JobOutbox,
    Project,
    ProjectAnalysis,
    ProjectPlan,
    ProjectRender,
    ProjectAsset,
)
from miraaj_api.schemas import (
    AnalysisRead,
    AssetRead,
    HealthRead,
    PlanRead,
    RenderRead,
    RenderRequest,
    ProjectRead,
    TargetDurationRequest,
    SceneRegenerationRequest,
)
from miraaj_api.script_analysis import (
    analyze_script_cached,
    assess_duration_target,
    estimate_duration,
)
from miraaj_api.storage import LocalStorageProvider
from miraaj_api.media_tools import media_tool
from miraaj_api.media_pipeline import probe_video, MediaProcessingError
from miraaj_api.director import EDIT_PLAN_SCHEMA, DirectorError, configured_director
from miraaj_api.timeline_builder import TimelineBuilder, TimelineValidationError
from jsonschema import Draft202012Validator
import json

settings = get_settings()
logger = logging.getLogger("miraaj.media")


def validate_media_tool(name: str) -> str:
    executable = media_tool(name)
    if executable is None:
        logger.warning("%s is not installed; video processing is unavailable", name)
        return "missing"
    try:
        result = subprocess.run(
            [executable, "-version"], capture_output=True, text=True, timeout=5, check=False
        )
        if result.returncode == 0 and result.stdout.startswith(f"{name} version"):
            logger.info("Validated %s: %s", name, result.stdout.splitlines()[0])
            return "ok"
    except (OSError, subprocess.TimeoutExpired):
        pass
    logger.error("%s was found but failed its version check", name)
    return "invalid"


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_media_tool("ffmpeg")
    validate_media_tool("ffprobe")
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Miraaj API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
storage = LocalStorageProvider(settings.storage_path)


@app.get("/health", response_model=HealthRead)
def health(db: Session = Depends(get_db)) -> HealthRead:
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:
        database = "unavailable"
    try:
        with Redis.from_url(settings.redis_url, socket_connect_timeout=1) as redis_client:
            redis_client.ping()
        redis = "ok"
    except Exception:
        redis = "unavailable"
    ffmpeg = validate_media_tool("ffmpeg")
    ffprobe = validate_media_tool("ffprobe")
    healthy = database == redis == ffmpeg == ffprobe == "ok"
    return HealthRead(
        status="ok" if healthy else "degraded",
        database=database,
        redis=redis,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )


@app.post("/api/projects", response_model=ProjectRead, status_code=201)
async def create_project(
    name: str = Form(..., min_length=1, max_length=200),
    script_text: str = Form(..., min_length=1),
    video: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Project:
    if not name.strip():
        raise HTTPException(status_code=422, detail="Project name cannot be blank.")
    if not script_text.strip():
        raise HTTPException(status_code=422, detail="Script cannot be blank.")
    if not video.content_type or not video.content_type.startswith("video/"):
        raise HTTPException(status_code=415, detail="Upload a video file.")
    project = Project(
        name=name.strip(),
        status="created",
        source_video_path="pending",
        script_text=script_text.strip(),
    )
    script_analysis = analyze_script_cached(script_text, settings.storage_path / ".cache")
    duration_estimate = estimate_duration(script_analysis)
    project.analysis = ProjectAnalysis(
        status="queued",
        script_analysis=script_analysis,
        duration_estimate=duration_estimate,
        target_duration=float(duration_estimate["recommended_duration"]),
        duration_fit=assess_duration_target(
            duration_estimate, duration_estimate["recommended_duration"]
        ),
    )
    db.add(project)
    db.flush()
    saved_video_path: str | None = None
    try:
        if video.size is not None and video.size > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(
                status_code=413, detail=f"Video exceeds the {settings.max_upload_mb} MB limit."
            )
        project.source_video_path = await storage.save_upload(project.id, video)
        saved_video_path = project.source_video_path
        job = Job(project_id=project.id, kind="media_analysis", status="queued")
        db.add(job)
        db.flush()
        db.add(JobOutbox(job_id=job.id))
        db.commit()
        db.refresh(project)
    except Exception:
        db.rollback()
        if saved_video_path:
            Path(saved_video_path).unlink(missing_ok=True)
        raise
    return project


@app.get("/api/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.created_at.desc())).all())


@app.get("/api/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


@app.get("/api/projects/{project_id}/analysis", response_model=AnalysisRead)
def get_analysis(project_id: str, db: Session = Depends(get_db)) -> ProjectAnalysis:
    analysis = db.get(ProjectAnalysis, project_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Project analysis not found.")
    return analysis


@app.post("/api/projects/{project_id}/analysis/retry", response_model=ProjectRead, status_code=202)
def retry_analysis(project_id: str, db: Session = Depends(get_db)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    if project.analysis is None:
        raise HTTPException(status_code=409, detail="Project analysis record is missing.")
    if project.analysis.status in {"queued", "analyzing"}:
        raise HTTPException(status_code=409, detail="Media analysis is already running.")
    if project.analysis.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed media analysis can be retried.")
    if not Path(project.source_video_path).is_file():
        raise HTTPException(status_code=409, detail="The original uploaded recording is missing.")
    project.analysis.status = "queued"
    project.analysis.error = None
    project.status = "created"
    job = Job(project_id=project_id, kind="media_analysis", status="queued")
    db.add(job)
    db.flush()
    db.add(JobOutbox(job_id=job.id))
    db.commit()
    db.refresh(project)
    return project


@app.put("/api/projects/{project_id}/target-duration", response_model=AnalysisRead)
def set_target_duration(
    project_id: str, request: TargetDurationRequest, db: Session = Depends(get_db)
) -> ProjectAnalysis:
    analysis = db.get(ProjectAnalysis, project_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Project analysis not found.")
    analysis.target_duration = request.seconds
    analysis.duration_fit = assess_duration_target(analysis.duration_estimate, request.seconds)
    db.commit()
    db.refresh(analysis)
    return analysis


@app.post("/api/projects/{project_id}/plan", response_model=PlanRead, status_code=202)
def create_plan(project_id: str, db: Session = Depends(get_db)) -> ProjectPlan:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    if project.analysis is None or project.analysis.status != "ready":
        raise HTTPException(status_code=409, detail="Media analysis must finish before planning.")
    existing = db.get(ProjectPlan, project_id)
    if existing is not None and existing.status in {"queued", "planning", "ready"}:
        return existing
    if existing is None:
        existing = ProjectPlan(project_id=project_id, provider=get_settings().director_provider)
        db.add(existing)
    else:
        existing.status, existing.error, existing.edit_plan, existing.timeline = (
            "queued",
            None,
            None,
            None,
        )
    job = Job(project_id=project_id, kind="director", status="queued")
    db.add(job)
    db.flush()
    db.add(JobOutbox(job_id=job.id))
    db.commit()
    db.refresh(existing)
    return existing


@app.get("/api/projects/{project_id}/plan", response_model=PlanRead)
def get_plan(project_id: str, db: Session = Depends(get_db)) -> ProjectPlan:
    result = db.get(ProjectPlan, project_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Plan not found.")
    return result


@app.post("/api/projects/{project_id}/scenes/{scene_id}/regenerate", response_model=PlanRead)
def regenerate_scene(
    project_id: str,
    scene_id: str,
    request: SceneRegenerationRequest,
    db: Session = Depends(get_db),
) -> ProjectPlan:
    """Regenerate one scene's presentation while retaining its validated source range."""
    project = db.get(Project, project_id)
    plan = db.get(ProjectPlan, project_id)
    if project is None or plan is None:
        raise HTTPException(status_code=404, detail="Project or Director plan not found.")
    if plan.status != "ready" or not plan.edit_plan or not plan.timeline:
        raise HTTPException(status_code=409, detail="A ready Director plan is required.")
    scenes = plan.edit_plan.get("scenes", [])
    current = next((scene for scene in scenes if scene.get("id") == scene_id), None)
    if current is None:
        raise HTTPException(status_code=404, detail="Scene not found in this plan.")
    try:
        director = configured_director()
    except DirectorError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if director.provider is None:
        raise HTTPException(
            status_code=409,
            detail="Scene regeneration requires the configured local or Gemini LLM provider.",
        )
    analysis = project.analysis
    context = {
        "task": "Regenerate only the selected scene presentation. Preserve source range and timing exactly.",
        "instruction": request.instruction,
        "scene": current,
        "source_duration_seconds": float(
            (analysis.video_metadata or {}).get("duration_seconds") or 0
        )
        if analysis
        else 0,
        "script": project.script_text,
        "transcript": (analysis.transcript or {}).get("words", []) if analysis else [],
        "style_id": plan.edit_plan.get("style_id", "modern_creator_v1"),
    }
    scene_schema = {
        **EDIT_PLAN_SCHEMA["$defs"]["scene"],
        "$schema": EDIT_PLAN_SCHEMA["$schema"],
        "$defs": EDIT_PLAN_SCHEMA["$defs"],
    }
    try:
        raw = director.provider.generate(context, scene_schema)
        replacement = json.loads(raw)
        errors = sorted(
            Draft202012Validator(scene_schema).iter_errors(replacement),
            key=lambda error: list(error.path),
        )
        if errors:
            repair = "; ".join(error.message for error in errors)
            replacement = json.loads(
                director.provider.generate(context, scene_schema, repair=repair)
            )
        for locked in (
            "id",
            "source_start",
            "source_end",
            "timeline_start",
            "duration",
            "layer",
            "channel",
        ):
            if locked in current:
                replacement[locked] = current[locked]
            elif locked == "layer":
                replacement[locked] = "base"
            elif locked == "channel":
                replacement[locked] = "video"
        if current.get("layer", "base") == "base":
            # Keep base-scene component semantics stable so speaker audio cannot
            # disappear when a scene is regenerated.
            replacement["type"] = current["type"]
        updated = {
            **plan.edit_plan,
            "scenes": [replacement if scene["id"] == scene_id else scene for scene in scenes],
        }
        style_path = (
            Path(__file__).resolve().parents[4]
            / "packages"
            / "style-system"
            / "modern_creator_v1.json"
        )
        style = json.loads(style_path.read_text(encoding="utf-8"))
        assets = db.query(ProjectAsset).filter(ProjectAsset.project_id == project_id).all()
        available_assets = {
            asset.id: {"kind": asset.kind, "metadata": asset.asset_metadata or {}}
            for asset in assets
        }
        video_analysis = analysis.video_analysis or {} if analysis else {}
        face_boxes = video_analysis.get("face_analysis", {}).get("samples", [])
        timeline = TimelineBuilder().build(
            updated,
            float((analysis.video_metadata or {}).get("duration_seconds") or 0) if analysis else 0,
            style=style,
            face_boxes=face_boxes,
            available_assets=available_assets,
        )
    except (ValueError, TypeError, KeyError, TimelineValidationError) as error:
        raise HTTPException(
            status_code=422, detail=f"Regenerated scene failed validation: {error}"
        ) from error
    except Exception as error:
        logger.exception("Scene regeneration failed for %s/%s", project_id, scene_id)
        raise HTTPException(
            status_code=502, detail=f"Scene regeneration provider failed: {error}"
        ) from error
    plan.edit_plan, plan.timeline = updated, timeline
    plan.provider = settings.director_provider
    plan.error = None
    db.commit()
    db.refresh(plan)
    return plan


@app.post("/api/projects/{project_id}/assets", response_model=AssetRead, status_code=201)
async def upload_project_asset(
    project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> ProjectAsset:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    plan = db.get(ProjectPlan, project_id)
    if plan is not None and plan.status in {"queued", "planning"}:
        raise HTTPException(
            status_code=409,
            detail="Wait for the current Director job to finish before uploading an asset.",
        )
    name = Path(file.filename or "").name
    suffix = Path(name).suffix.lower()
    image_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    video_suffixes = {".mp4", ".mov", ".webm"}
    if suffix in image_suffixes and file.content_type in {"image/png", "image/jpeg", "image/webp"}:
        kind = "image"
    elif suffix in video_suffixes and file.content_type in {
        "video/mp4",
        "video/quicktime",
        "video/webm",
    }:
        kind = "video"
    else:
        raise HTTPException(
            status_code=415,
            detail="Upload a PNG, JPEG, WebP, MP4, MOV, or WebM asset with its matching content type.",
        )
    asset_id = str(uuid.uuid4())
    directory = settings.storage_path / project_id / "assets"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{asset_id}{suffix}"
    total = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Asset exceeds the {settings.max_upload_mb} MB limit.",
                    )
                output.write(chunk)
        if total == 0:
            raise HTTPException(status_code=422, detail="Uploaded asset is empty.")
        if kind == "video":
            try:
                metadata = probe_video(destination, media_tool("ffprobe"))
            except MediaProcessingError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
        else:
            import cv2

            image = cv2.imread(str(destination))
            if image is None:
                raise HTTPException(status_code=422, detail="The uploaded image cannot be decoded.")
            metadata = {"width": int(image.shape[1]), "height": int(image.shape[0]), "bytes": total}
        asset = ProjectAsset(
            id=asset_id,
            project_id=project_id,
            kind=kind,
            name=name or f"asset{suffix}",
            path=str(destination),
            content_type=file.content_type or "application/octet-stream",
            asset_metadata=metadata,
        )
        db.add(asset)
        if plan is not None:
            plan.status, plan.error, plan.edit_plan, plan.timeline = (
                "failed",
                "Assets changed; create a new validated plan before rendering.",
                None,
                None,
            )
        db.commit()
        db.refresh(asset)
        return asset
    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise


@app.get("/api/projects/{project_id}/assets", response_model=list[AssetRead])
def list_project_assets(project_id: str, db: Session = Depends(get_db)) -> list[ProjectAsset]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return list(
        db.scalars(
            select(ProjectAsset)
            .where(ProjectAsset.project_id == project_id)
            .order_by(ProjectAsset.created_at)
        ).all()
    )


@app.post("/api/projects/{project_id}/renders", response_model=RenderRead, status_code=202)
def create_render(
    project_id: str, request: RenderRequest, db: Session = Depends(get_db)
) -> ProjectRender:
    project = db.get(Project, project_id)
    plan = db.get(ProjectPlan, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    if plan is None or plan.status != "ready" or plan.timeline is None:
        raise HTTPException(
            status_code=409, detail="A validated timeline is required before rendering."
        )
    if request.profile not in {"vertical_1080", "vertical_4k"}:
        raise HTTPException(status_code=422, detail="Unknown render profile.")
    if not Path(project.source_video_path).is_file():
        raise HTTPException(status_code=409, detail="Original source footage is missing.")
    job = Job(project_id=project_id, kind="render", status="queued")
    db.add(job)
    db.flush()
    render = ProjectRender(
        project_id=project_id, job_id=job.id, profile=request.profile, volume=request.volume
    )
    db.add(render)
    db.add(JobOutbox(job_id=job.id))
    db.commit()
    db.refresh(render)
    return render


@app.get("/api/projects/{project_id}/renders/latest", response_model=RenderRead)
def get_latest_render(project_id: str, db: Session = Depends(get_db)) -> ProjectRender:
    render = db.scalar(
        select(ProjectRender)
        .where(ProjectRender.project_id == project_id)
        .order_by(ProjectRender.updated_at.desc())
    )
    if render is None:
        raise HTTPException(status_code=404, detail="No render job found.")
    return render


@app.get("/api/renders/{render_id}", response_model=RenderRead)
def get_render(render_id: str, db: Session = Depends(get_db)) -> ProjectRender:
    render = db.get(ProjectRender, render_id)
    if render is None:
        raise HTTPException(status_code=404, detail="Render job not found.")
    return render


@app.get("/api/renders/{render_id}/file")
def download_render(render_id: str, db: Session = Depends(get_db)) -> FileResponse:
    render = db.get(ProjectRender, render_id)
    if render is None or render.status != "completed" or not render.output_path:
        raise HTTPException(status_code=409, detail="Render is not ready for download.")
    path = Path(render.output_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Rendered file is missing.")
    return FileResponse(path, media_type="video/mp4", filename=f"miraaj-{render.project_id}.mp4")
