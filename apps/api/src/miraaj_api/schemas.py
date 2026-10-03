from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JobRead(BaseModel):
    id: str
    kind: str
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProjectRead(BaseModel):
    id: str
    name: str
    status: str
    source_video_path: str
    script_text: str
    created_at: datetime
    jobs: list[JobRead] = Field(default_factory=list)
    analysis: "AnalysisRead | None" = None
    model_config = ConfigDict(from_attributes=True)


class AnalysisRead(BaseModel):
    project_id: str
    status: str
    content_hash: str | None = None
    video_metadata: dict | None = None
    video_analysis: dict | None = None
    audio_analysis: dict | None = None
    transcript: dict | None = None
    script_analysis: dict
    duration_estimate: dict
    target_duration: float | None = None
    duration_fit: dict | None = None
    error: str | None = None
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TargetDurationRequest(BaseModel):
    seconds: float = Field(gt=0, le=600)


class PlanRead(BaseModel):
    project_id: str
    status: str
    provider: str
    edit_plan: dict | None = None
    timeline: dict | None = None
    error: str | None = None
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SceneRegenerationRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=2000)


class RenderRequest(BaseModel):
    profile: str = "vertical_1080"
    volume: float = Field(default=1, ge=0, le=1)


class RenderRead(BaseModel):
    id: str
    project_id: str
    job_id: str
    status: str
    stage: str
    progress: float
    profile: str
    volume: float
    output_path: str | None = None
    error: str | None = None
    source_width: int | None = None
    source_height: int | None = None
    output_width: int | None = None
    output_height: int | None = None
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AssetRead(BaseModel):
    id: str
    project_id: str
    kind: str
    name: str
    content_type: str
    metadata: dict = Field(validation_alias="asset_metadata")
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


ProjectRead.model_rebuild()


class HealthRead(BaseModel):
    status: str
    database: str
    redis: str
    ffmpeg: str
    ffprobe: str
