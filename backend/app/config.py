"""Application settings — the single source of truth for configuration.

Values come from the process environment (12-factor); `.env` is read in dev as a
convenience. Every env var from `plan.md` §8 is represented here with a typed
field and a sensible dev default.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["dev", "staging", "prod"]
ContentProviderName = Literal["fixture", "notebooklm"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- core ----
    app_env: Environment = "dev"
    session_secret: str = "dev-only-not-secret"
    database_url: str = "postgresql+psycopg://shikshak:shikshak@postgres:5432/shikshak"
    redis_url: str = "redis://redis:6379/0"
    media_root: str = "/data/media"
    media_gc_keep_versions: int = 3
    public_base_url: str = "http://localhost:5173"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    log_level: str = "info"

    # ---- content provider ----
    content_provider: ContentProviderName = "fixture"
    mcp_endpoint: str = "http://mcp:7332"
    mcp_timeout_text_sec: int = 360
    mcp_timeout_audio_sec: int = 1200
    max_module_fanout: int = 2

    # ---- auth ----
    admin_session_ttl_hours: int = 8
    student_session_ttl_days: int = 30
    login_rate_limit: str = "10/5m"
    password_reset_enabled: bool = True

    # ---- email ----
    smtp_url: str = "smtp://mailhog:1025"
    email_from: str = "no-reply@shikshak.local"

    # ---- celery ----
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # ---- observability ----
    sentry_dsn: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Parse the env var as a comma-separated list (``a,b,c``)."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def db_url_sync(self) -> str:
        """DSN without the SQLAlchemy driver marker, for tools that want libpq form."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
