"""T009 — admin auth API; scope separation from students (spec.md §5.1, D3)."""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin

ADMIN_PW = "admin-console-pw-1"
STUDENT = {"email": "stu@example.com", "password": "student-pw-12345", "display_name": "Stu"}


def _seed(db_session: Session, email: str = "boss@example.com") -> None:
    seed_admin(db_session, email=email, display_name="Boss", password=ADMIN_PW)
    db_session.flush()


def test_admin_login_me_logout(client: TestClient, db_session: Session) -> None:
    _seed(db_session)
    login = client.post(
        "/api/admin/auth/login", json={"email": "boss@example.com", "password": ADMIN_PW}
    )
    assert login.status_code == status.HTTP_200_OK
    assert "sdp_admin" in login.cookies
    assert "httponly" in login.headers.get("set-cookie", "").lower()

    me = client.get("/api/admin/auth/me")
    assert me.status_code == status.HTTP_200_OK
    assert me.json()["user"]["role"] == "admin"

    logout = client.post(
        "/api/admin/auth/logout", headers={"X-CSRF-Token": client.cookies["sdp_csrf"]}
    )
    assert logout.status_code == status.HTTP_204_NO_CONTENT
    assert client.get("/api/admin/auth/me").status_code == status.HTTP_401_UNAUTHORIZED


def test_admin_login_wrong_password_is_401(client: TestClient, db_session: Session) -> None:
    _seed(db_session)
    resp = client.post(
        "/api/admin/auth/login", json={"email": "boss@example.com", "password": "nope-nope-nope"}
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json()["error"]["code"] == "invalid_credentials"


def test_admin_me_without_cookie_is_401(client: TestClient) -> None:
    assert client.get("/api/admin/auth/me").status_code == status.HTTP_401_UNAUTHORIZED


def test_student_cookie_is_rejected_by_admin_me(client: TestClient) -> None:
    reg = client.post("/api/student/auth/register", json=STUDENT)
    assert reg.status_code == status.HTTP_201_CREATED
    # student cookie is now in the client jar
    resp = client.get("/api/admin/auth/me")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json()["error"]["code"] == "unauthorized"


def test_student_credentials_cannot_log_into_admin(client: TestClient) -> None:
    client.post("/api/student/auth/register", json=STUDENT)
    client.cookies.clear()
    resp = client.post(
        "/api/admin/auth/login",
        json={"email": STUDENT["email"], "password": STUDENT["password"]},
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


def test_no_admin_register_endpoint(client: TestClient) -> None:
    resp = client.post(
        "/api/admin/auth/register",
        json={"email": "x@example.com", "password": "x", "display_name": "X"},
    )
    assert resp.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_405_METHOD_NOT_ALLOWED)
    paths = client.get("/api/openapi.json").json()["paths"]
    assert not any("admin" in p and p.endswith("/register") for p in paths)
