"""T010 — RBAC guard, CSRF, and security headers (US-N1)."""

from __future__ import annotations

import pytest
from fastapi import status
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.main import create_app

# Admin endpoints that exist *before* a session and are therefore exempt from
# the "must be an authenticated admin" rule.
_PRE_AUTH = {
    ("/api/admin/auth/login", "POST"),
    ("/api/admin/auth/logout", "POST"),
    # password reset (O6) is deliberately public — you're logged out when using it
    ("/api/admin/auth/password-reset/request", "POST"),
    ("/api/admin/auth/password-reset/confirm", "POST"),
}


def _guarded_admin_routes() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for route in create_app().routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/admin/"):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (route.path, method) not in _PRE_AUTH:
                out.append((route.path, method))
    return out


ADMIN_ROUTES = _guarded_admin_routes()


def _seed_admin_and_login(client: TestClient, db_session: Session) -> str:
    seed_admin(
        db_session, email="root@example.com", display_name="Root", password="root-console-pw-1"
    )
    db_session.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "root@example.com", "password": "root-console-pw-1"}
    )
    return client.cookies["sdp_csrf"]


@pytest.mark.parametrize(("path", "method"), ADMIN_ROUTES)
def test_admin_routes_reject_anonymous(client: TestClient, path: str, method: str) -> None:
    resp = client.request(method, path)
    assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.parametrize(("path", "method"), ADMIN_ROUTES)
def test_admin_routes_reject_student_session(client: TestClient, path: str, method: str) -> None:
    client.post(
        "/api/student/auth/register",
        json={"email": "n1@example.com", "password": "student-pw-12345", "display_name": "N1"},
    )
    headers = {"X-CSRF-Token": client.cookies.get("sdp_csrf", "")}
    resp = client.request(method, path, headers=headers)
    assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


def test_csrf_required_on_state_change(client: TestClient, db_session: Session) -> None:
    csrf = _seed_admin_and_login(client, db_session)

    # missing header
    assert (
        client.post("/api/admin/auth/logout", headers={"X-CSRF-Token": ""}).status_code
        == status.HTTP_403_FORBIDDEN
    )
    # wrong header
    bad = client.post("/api/admin/auth/logout", headers={"X-CSRF-Token": "not-the-token"})
    assert bad.status_code == status.HTTP_403_FORBIDDEN
    assert bad.json()["error"]["code"] == "csrf_failed"
    # correct header
    ok = client.post("/api/admin/auth/logout", headers={"X-CSRF-Token": csrf})
    assert ok.status_code == status.HTTP_204_NO_CONTENT


def test_login_sets_readable_csrf_cookie(client: TestClient, db_session: Session) -> None:
    _seed_admin_and_login(client, db_session)
    set_cookie = " ".join(
        h for k, h in client.get("/api/admin/auth/me").headers.items() if k.lower() == "set-cookie"
    )
    # sdp_csrf is set at login; assert the value is present and it is NOT HttpOnly
    assert "sdp_csrf" in client.cookies
    assert "sdp_csrf" not in set_cookie or "httponly" not in set_cookie.lower()


def test_security_headers_present(client: TestClient) -> None:
    h = client.get("/healthz").headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "strict-origin-when-cross-origin"
    # HSTS only in prod
    assert "strict-transport-security" not in h


def test_hsts_emitted_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    prod = Settings(
        app_env="prod",
        database_url="postgresql+psycopg://app:real-pw@db:5432/shikshak",
        public_base_url="https://learn.example.org",
        smtp_url="smtps://mailer:pw@smtp.example.org",
    )
    monkeypatch.setattr("app.config.get_settings", lambda: prod)
    with TestClient(create_app(prod)) as prod_client:
        assert "strict-transport-security" in prod_client.get("/healthz").headers
