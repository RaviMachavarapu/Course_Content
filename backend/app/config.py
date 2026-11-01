"""Application settings — the single source of truth for configuration.

Values come from the process environment (12-factor); `.env` is read in dev as a
convenience. Every env var from `plan.md` §8 is represented here with a typed
field and a sensible dev default.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import parse_qs, unquote, urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["dev", "staging", "prod"]
ContentProviderName = Literal["fixture", "notebooklm"]

_DEV_DB_PASSWORD = "shikshak"
_DEV_PUBLIC_BASE_URL = "http://localhost:5173"
_DEV_SMTP_URL = "smtp://mailhog:1025"
_DEV_SMTP_HOST = "mailhog"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
_DEV_DEVICE_COOKIE_SECRET = "dev-only-device-cookie-secret-change-me"
_MIN_DEVICE_COOKIE_SECRET_LEN = 32
#: the dev compose stack's Redis password (docker-compose.yml)
_DEV_REDIS_PASSWORD = "dev-only-redis-password-change-me"
_DEV_REDIS = f"redis://:{_DEV_REDIS_PASSWORD}@redis:6379"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- core ----
    app_env: Environment = "dev"
    database_url: str = "postgresql+psycopg://shikshak:shikshak@postgres:5432/shikshak"
    redis_url: str = f"{_DEV_REDIS}/0"
    media_root: str = "/data/media"
    media_gc_keep_versions: int = 3
    public_base_url: str = _DEV_PUBLIC_BASE_URL
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    log_level: str = "info"

    # ---- content provider ----
    content_provider: ContentProviderName = "fixture"
    mcp_endpoint: str = "http://mcp:7332"
    #: how long a run waits for NotebookLM to finish one artifact. Live slide decks
    #: have taken > 6 min; a run that still times out keeps NotebookLM's request so
    #: Retry goes on waiting for the same artifact (no new generation).
    mcp_timeout_text_sec: int = 30 * 60
    mcp_timeout_audio_sec: int = 45 * 60
    #: generation jobs: heartbeat cadence while running; the reaper fails a running
    #: job silent for `job_stale_running_sec` and a queued one untouched for
    #: `job_stale_queued_sec` (lost message), so cards never sit on "Generating…".
    job_heartbeat_sec: int = 60
    job_stale_running_sec: int = 900
    job_stale_queued_sec: int = 6 * 3600
    #: a queued job untouched this long whose message the broker no longer holds is
    #: sent again (outbox); one still in the broker (a real backlog) is kept alive
    job_redispatch_after_sec: int = 600
    job_max_redispatches: int = 3
    #: a running job that made no progress this long (alive but stuck) stops beating,
    #: so the reaper fails it `job_stale_running_sec` later
    job_stall_sec: int = 45 * 60
    #: Celery soft time limit per generation job (then a 5-minute hard limit): frees
    #: a worker slot held by a stuck call. Below the broker's 4 h visibility timeout.
    job_time_limit_text_sec: int = 3 * 3600
    job_time_limit_audio_sec: int = 3 * 3600 + 1800
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
    #: idle timeout: a session ends after this long without a request (each
    #: authenticated request renews it, cheaply — see auth.sessions)
    admin_session_ttl_hours: int = Field(default=8, ge=1)
    student_session_ttl_days: int = Field(default=30, ge=1)
    #: absolute maximum: however active, a session ends this long after sign-in
    admin_session_max_days: int = Field(default=7, ge=1)
    student_session_max_days: int = Field(default=30, ge=1)
    #: failed logins per client IP, sliding window (successes don't count);
    #: beyond it 429 until the oldest failure leaves the window
    login_rate_limit: str = "100/15m"
    #: per-email (and per-device) failures are counted over this sliding window
    login_failure_window_sec: int = Field(default=900, ge=1)
    #: failures per email with no delay; from the next failure on, the next
    #: attempt waits base, 2*base, 4*base … seconds (capped at max)
    login_free_failures: int = Field(default=5, ge=0)
    #: the same, for attempts carrying a valid trusted-device cookie
    login_device_free_failures: int = Field(default=10, ge=0)
    login_delay_base_sec: int = Field(default=2, ge=1)
    login_delay_max_sec: int = Field(default=60, ge=1)
    #: signs the trusted-device cookie (sdp_device_<scope>); required outside dev
    device_cookie_secret: str = _DEV_DEVICE_COOKIE_SECRET
    device_cookie_max_age_days: int = Field(default=180, ge=1)
    #: register attempts per client IP (each one costs an Argon2 hash)
    register_rate_limit: str = "100/1h"
    #: password-reset requests per client IP (429 beyond); per email the cap is
    #: silent (still 202, no more mail) — see auth.password_reset
    password_reset_rate_limit: str = "30/1h"
    password_reset_enabled: bool = True

    # ---- email ----
    smtp_url: str = _DEV_SMTP_URL
    email_from: str = "no-reply@shikshak.local"

    # ---- celery ----
    celery_broker_url: str = f"{_DEV_REDIS}/1"
    celery_result_backend: str = f"{_DEV_REDIS}/2"

    # ---- observability ----
    sentry_dsn: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Parse the env var as a comma-separated list (``a,b,c``)."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("login_rate_limit", "register_rate_limit", "password_reset_rate_limit")
    @classmethod
    def _rate_spec(cls, value: str) -> str:
        """``N/<window>`` with N >= 1 and a non-empty window: a 0 limit
        ("disable") made every login fail with a 500."""
        from app.auth.ratelimit import parse_rate

        limit, window = parse_rate(value)
        if limit < 1 or window < 1:
            raise ValueError(f"must be N/<window> with N >= 1 and a window > 0 (got {value!r})")
        return value

    @model_validator(mode="after")
    def _no_dev_defaults_outside_dev(self) -> Settings:
        """Staging/prod refuse to start on dev or missing secrets: the database
        and Redis need a password that isn't the dev one, device cookies a
        signing secret of 32+ characters that isn't the dev one, and reset
        links an https PUBLIC_BASE_URL that isn't localhost (session cookies
        are Secure outside dev). Prod must not "send" reset mail into mailhog
        or nowhere: a real SMTP_URL, or PASSWORD_RESET_ENABLED=false."""
        if self.app_env == "dev":
            return self
        problems: list[str] = []

        db_password = _url_password(self.database_url)
        if not db_password:
            problems.append("DATABASE_URL has no password")
        elif db_password == _DEV_DB_PASSWORD:
            problems.append("DATABASE_URL uses the dev credentials")

        base = urlsplit(self.public_base_url)
        if base.hostname in _LOCAL_HOSTS or not base.hostname:
            problems.append("PUBLIC_BASE_URL is localhost (reset links would point there)")
        elif base.scheme != "https":
            problems.append("PUBLIC_BASE_URL must be https (cookies are Secure outside dev)")

        if self.device_cookie_secret == _DEV_DEVICE_COOKIE_SECRET:
            problems.append("DEVICE_COOKIE_SECRET is the dev default")
        elif len(self.device_cookie_secret) < _MIN_DEVICE_COOKIE_SECRET_LEN:
            problems.append(
                f"DEVICE_COOKIE_SECRET must be at least {_MIN_DEVICE_COOKIE_SECRET_LEN} characters"
            )

        for name, url in (
            ("REDIS_URL", self.redis_url),
            ("CELERY_BROKER_URL", self.celery_broker_url),
            ("CELERY_RESULT_BACKEND", self.celery_result_backend),
        ):
            password = _url_password(url)
            if not password:
                problems.append(f"{name} has no Redis password")
            elif password == _DEV_REDIS_PASSWORD:
                problems.append(f"{name} uses the dev Redis password")

        if self.is_prod and self.password_reset_enabled:
            smtp_host = urlsplit(self.smtp_url).hostname
            if not smtp_host or smtp_host == _DEV_SMTP_HOST:
                problems.append(
                    "SMTP_URL is the dev mailhog or empty (or set PASSWORD_RESET_ENABLED=false)"
                )
        if self.is_prod and _smtp_credentials_in_clear(self.smtp_url):
            problems.append(
                "SMTP_URL sends its credentials unencrypted (use smtps:// or ?starttls=true)"
            )

        if problems:
            raise ValueError(f"APP_ENV={self.app_env}: " + "; ".join(problems))
        return self

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def db_url_sync(self) -> str:
        """DSN without the SQLAlchemy driver marker, for tools that want libpq form."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _smtp_credentials_in_clear(url: str) -> bool:
    """A plain ``smtp://`` URL with a user and without ``starttls=true``."""
    parts = urlsplit(url)
    if parts.scheme.lower() != "smtp" or not parts.username:
        return False
    starttls = parse_qs(parts.query).get("starttls", ["false"])[0].lower()
    return starttls not in {"1", "true", "yes", "on"}


def _url_password(url: str) -> str | None:
    """The password in a database/redis URL (None when there is none)."""
    password = urlsplit(url).password
    return unquote(password) if password else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
