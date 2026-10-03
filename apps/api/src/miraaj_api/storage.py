from pathlib import Path
from typing import Protocol

from fastapi import UploadFile


class StorageProvider(Protocol):
    async def save_upload(self, project_id: str, upload: UploadFile) -> str: ...


class LocalStorageProvider:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    async def save_upload(self, project_id: str, upload: UploadFile) -> str:
        directory = self.root / project_id
        directory.mkdir(parents=True, exist_ok=True)
        suffix = Path(upload.filename or "video.mp4").suffix.lower() or ".mp4"
        destination = directory / f"{project_id}_source{suffix}"
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                output.write(chunk)
        return str(destination)
