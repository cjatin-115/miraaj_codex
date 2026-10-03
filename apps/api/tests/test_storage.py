import asyncio
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.datastructures import Headers, UploadFile

from miraaj_api.storage import LocalStorageProvider


def test_local_storage_saves_upload_inside_project_directory() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as temporary_directory:
        root = Path(temporary_directory)

        async def save() -> str:
            upload = UploadFile(
                filename="camera take.MP4",
                file=BytesIO(b"sample video bytes"),
                headers=Headers({"content-type": "video/mp4"}),
            )
            return await LocalStorageProvider(root).save_upload("project-123", upload)

        stored_path = Path(asyncio.run(save()))
        assert stored_path.parent == root / "project-123"
        assert stored_path.name == "project-123_source.mp4"
        assert stored_path.suffix == ".mp4"
        assert stored_path.read_bytes() == b"sample video bytes"
