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

    # ---- PDF sources (NotebookLM rejects >200 MB or >500,000 words per source) ----
    source_part_max_bytes: int = 190 * 1024 * 1024
    source_part_max_words: int = 450_000
    notebook_max_sources: int = 300

    # ---- typeset service (Quarto PDFs) ----
    typeset_endpoint: str = "http://typeset:8080"
    #: a render can take ~150 s worst case (queue wait + fallback)
    typeset_timeout_sec: int = 180

    # ---- auth ----
    admin_session_ttl_hours: int = 8
    student_session_ttl_days: int = 30
    #: failed logins, per client IP and per email (successes don't count)
    login_rate_limit: str = "10/5m"
    #: register attempts per client IP (each one costs an Argon2 hash)
    register_rate_limit: str = "30/1h"
    #: password-reset requests per client IP (429 beyond); per email the cap is
    #: silent (still 202, no more mail) — see auth.password_reset
    password_reset_rate_limit: str = "10/1h"
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
