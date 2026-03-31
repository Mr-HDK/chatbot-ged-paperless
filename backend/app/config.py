from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")

    paperless_base_url: str = Field(alias="PAPERLESS_BASE_URL")
    paperless_token: str = Field(alias="PAPERLESS_TOKEN")

    ollama_base_url: str = Field(alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen3:4b", alias="OLLAMA_MODEL")

    top_k: int = Field(default=6, alias="TOP_K")
    max_context_chars: int = Field(default=12000, alias="MAX_CONTEXT_CHARS")
    request_timeout_seconds: float = Field(default=120.0, alias="REQUEST_TIMEOUT_SECONDS")
    cors_origins: str = Field(
        default="http://localhost:8080,http://127.0.0.1:8080,http://localhost:5173",
        alias="CORS_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [item.strip() for item in self.cors_origins.split(",")]
        return [item for item in origins if item]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
