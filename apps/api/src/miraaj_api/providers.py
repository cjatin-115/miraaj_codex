from pathlib import Path
from typing import Protocol


class StructuredAIProvider(Protocol):
    """Boundary for providers that return schema-validated structured results."""

    async def generate_json(self, *, prompt: str, schema: dict) -> dict: ...


class TranscriptionProvider(Protocol):
    """Boundary for local or hosted transcription implementations."""

    def transcribe(self, audio_path: Path) -> dict: ...


class ImageProvider(Protocol):
    """Optional image generation boundary; deterministic scene components are preferred."""

    async def generate_image(self, *, prompt: str, width: int, height: int) -> bytes: ...


class VideoProvider(Protocol):
    """Optional AI video boundary for concepts that native Remotion cannot communicate."""

    async def generate_video(
        self, *, prompt: str, duration_seconds: float, width: int, height: int
    ) -> bytes: ...
