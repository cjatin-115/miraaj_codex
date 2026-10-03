from miraaj_api.config import Settings


def test_current_environment_setting_names_are_supported(monkeypatch):
    monkeypatch.setenv("STORAGE_PATH", "data/projects")
    monkeypatch.setenv("RENDER_OUTPUT_PATH", "data/renders")
    monkeypatch.setenv("WHISPER_MODEL", "tiny")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL", "gemini-test")

    settings = Settings(_env_file=None)

    assert settings.storage_root == "data/projects"
    assert settings.render_output_path == "data/renders"
    assert settings.whisper_model_size == "tiny"
    assert settings.director_provider == "gemini"
    assert settings.local_llm_model == "gemini-test"


def test_real_local_llm_is_the_default_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("DIRECTOR_PROVIDER", raising=False)

    assert Settings(_env_file=None).director_provider == "local"
