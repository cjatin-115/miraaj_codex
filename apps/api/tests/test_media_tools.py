from miraaj_api import media_tools


def test_media_tool_prefers_host_ffmpeg_over_remotion_bundle(monkeypatch):
    monkeypatch.setattr(media_tools.shutil, "which", lambda name: f"host-{name}")

    assert media_tools.media_tool("ffmpeg") == "host-ffmpeg"
