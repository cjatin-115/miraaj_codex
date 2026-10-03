"""Prefer host FFmpeg for media jobs and use Remotion's bundled binaries as fallback."""

import shutil
import sys
import platform
from pathlib import Path


def media_tool(name: str) -> str | None:
    # The compositor package's FFmpeg is intentionally minimal and can fail its
    # direct CLI version check on Windows, so use a host build for standalone jobs.
    system_tool = shutil.which(name)
    if system_tool:
        return system_tool
    exe = f"{name}.exe" if sys.platform == "win32" else name
    root = Path(__file__).resolve().parents[4]
    machine = platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    package_platform = {
        "win32": f"win32-{arch}-msvc",
        "linux": f"linux-{arch}-gnu",
        "darwin": f"darwin-{arch}",
    }.get(sys.platform)
    if package_platform:
        bundled = root / "node_modules" / "@remotion" / f"compositor-{package_platform}" / exe
        if bundled.is_file():
            return str(bundled)
    return None
