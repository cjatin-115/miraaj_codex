from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    web_origin: str = "http://localhost:3000"
    database_url: str = "postgresql+psycopg://miraaj:miraaj@localhost:5432/miraaj"
    redis_url: str = "redis://localhost:6379/0"
    storage_root: str = Field(
        default="storage/projects", validation_alias=AliasChoices("STORAGE_PATH", "STORAGE_ROOT")
    )
    render_output_path: str = "storage/renders"
    max_upload_mb: int = 500
    whisper_model_size: str = Field(
        default="base", validation_alias=AliasChoices("WHISPER_MODEL", "WHISPER_MODEL_SIZE")
    )
    director_provider: str = Field(
        default="local", validation_alias=AliasChoices("LLM_PROVIDER", "DIRECTOR_PROVIDER")
    )
    local_llm_url: str = "http://localhost:11434"
    local_llm_model: str = Field(
        default="llama3.2", validation_alias=AliasChoices("LLM_MODEL", "LOCAL_LLM_MODEL")
    )
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_root)
        return self._resolve(path)

    @property
    def render_path(self) -> Path:
        return self._resolve(Path(self.render_output_path))

    @staticmethod
    def _resolve(path: Path) -> Path:
        return (
            path if path.is_absolute() else (Path(__file__).resolve().parents[4] / path).resolve()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
