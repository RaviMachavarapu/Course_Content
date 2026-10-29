"""Outside dev, refuse to start with the dev defaults (review 2026-10-28)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app

_REAL = {
    "database_url": "postgresql+psycopg://app:s3cr3t-pw@db.internal:5432/shikshak",
    "public_base_url": "https://learn.example.org",
    "smtp_url": "smtps://mailer:pw@smtp.example.org",
    "device_cookie_secret": "a-long-random-production-secret-value",
}


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_real_values_are_accepted(env: str) -> None:
    assert _settings(app_env=env, **_REAL).app_env == env


def test_dev_keeps_its_defaults() -> None:
    assert _settings(app_env="dev").app_env == "dev"


@pytest.mark.parametrize("env", ["staging", "prod"])
@pytest.mark.parametrize(
    ("field", "dev_value"),
    [
        ("database_url", "postgresql+psycopg://shikshak:shikshak@postgres:5432/shikshak"),
        ("database_url", "postgresql+psycopg://shikshak:shikshak@db.internal:5432/other"),
        ("public_base_url", "http://localhost:5173"),
    ],
)
def test_dev_defaults_are_refused_outside_dev(env: str, field: str, dev_value: str) -> None:
    with pytest.raises(ValidationError, match=field.upper()):
        _settings(app_env=env, **{**_REAL, field: dev_value})


def test_prod_refuses_the_dev_mail_relay_while_reset_is_on() -> None:
    with pytest.raises(ValidationError, match="SMTP_URL"):
        _settings(app_env="prod", **{**_REAL, "smtp_url": "smtp://mailhog:1025"})
    off = _settings(
        app_env="prod", password_reset_enabled=False, **{**_REAL, "smtp_url": "smtp://mailhog:1025"}
    )
    assert off.password_reset_enabled is False


@pytest.mark.parametrize("env", ["staging", "prod"])
@pytest.mark.parametrize("secret", ["dev-only-device-cookie-secret-change-me", "", "x", "s" * 31])
def test_device_cookie_secret_must_be_set_outside_dev(env: str, secret: str) -> None:
    with pytest.raises(ValidationError, match="DEVICE_COOKIE_SECRET"):
        _settings(app_env=env, **{**_REAL, "device_cookie_secret": secret})


def test_a_32_character_device_cookie_secret_is_enough() -> None:
    assert _settings(app_env="prod", **{**_REAL, "device_cookie_secret": "s" * 32})


def test_dev_has_a_device_cookie_secret_default() -> None:
    assert _settings(app_env="dev").device_cookie_secret


def test_session_secret_is_gone() -> None:
    assert not hasattr(_settings(), "session_secret")


def test_api_docs_are_hidden_in_prod() -> None:
    with TestClient(create_app(_settings(app_env="prod", **_REAL))) as c:
        assert c.get("/api/docs").status_code == 404
        assert c.get("/api/openapi.json").status_code == 404
    with TestClient(create_app(_settings(app_env="dev"))) as c:
        assert c.get("/api/openapi.json").status_code == 200
