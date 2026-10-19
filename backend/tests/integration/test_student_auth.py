"""T008 — student auth API (spec.md §5.1)."""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient

from app.auth.ratelimit import parse_rate
from app.config import get_settings

GOOD_PW = "sup3r-secret-pw"
REG = {"email": "sam@example.com", "password": GOOD_PW, "display_name": "Sam"}


def _register(client: TestClient, **over: object) -> object:
    return client.post("/api/student/auth/register", json={**REG, **over})


def test_register_sets_httponly_cookie_and_returns_user(client: TestClient) -> None:
    resp = _register(client)
    assert resp.status_code == status.HTTP_201_CREATED
    body = resp.json()
    assert body["user"]["email"] == "sam@example.com"
    assert body["user"]["role"] == "student"
    assert body["user"]["display_name"] == "Sam"
    assert "sdp_student" in resp.cookies
    assert "httponly" in resp.headers.get("set-cookie", "").lower()


def test_register_rejects_weak_password(client: TestClient) -> None:
    resp = _register(client, password="short")
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert resp.json()["error"]["code"] == "weak_password"


def test_register_duplicate_email_conflicts(client: TestClient) -> None:
    assert _register(client).status_code == status.HTTP_201_CREATED
    resp = _register(client, display_name="Other")
    assert resp.status_code == status.HTTP_409_CONFLICT
    assert resp.json()["error"]["code"] == "email_taken"


def test_login_then_me_round_trip(client: TestClient) -> None:
    _register(client)
    client.cookies.clear()

    resp = client.post(
        "/api/student/auth/login", json={"email": "SAM@example.com", "password": GOOD_PW}
    )
    assert resp.status_code == status.HTTP_200_OK
    assert "sdp_student" in resp.cookies

    me = client.get("/api/student/auth/me")
    assert me.status_code == status.HTTP_200_OK
    assert me.json()["user"]["email"] == "sam@example.com"


def test_login_wrong_password_is_401_generic(client: TestClient) -> None:
    _register(client)
    client.cookies.clear()
    resp = client.post(
        "/api/student/auth/login", json={"email": "sam@example.com", "password": "wrong-password-x"}
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json()["error"]["code"] == "invalid_credentials"


def test_login_unknown_email_is_401(client: TestClient) -> None:
    resp = client.post(
        "/api/student/auth/login", json={"email": "nobody@example.com", "password": GOOD_PW}
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


def test_me_without_cookie_is_401(client: TestClient) -> None:
    resp = client.get("/api/student/auth/me")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert resp.json()["error"]["code"] == "unauthorized"


def test_logout_requires_csrf_then_clears_session(client: TestClient) -> None:
    _register(client)
    assert client.get("/api/student/auth/me").status_code == status.HTTP_200_OK

    # no X-CSRF-Token header -> rejected
    assert client.post("/api/student/auth/logout").status_code == status.HTTP_403_FORBIDDEN

    csrf = client.cookies["sdp_csrf"]
    out = client.post("/api/student/auth/logout", headers={"X-CSRF-Token": csrf})
    assert out.status_code == status.HTTP_204_NO_CONTENT

    assert client.get("/api/student/auth/me").status_code == status.HTTP_401_UNAUTHORIZED


def test_login_is_rate_limited(client: TestClient) -> None:
    payload = {"email": "flood@example.com", "password": "whatever-nope"}
    limit, _window = parse_rate(get_settings().login_rate_limit)
    seen_429 = False
    for _ in range(limit + 2):
        code = client.post("/api/student/auth/login", json=payload).status_code
        if code == status.HTTP_429_TOO_MANY_REQUESTS:
            seen_429 = True
            break
        assert code == status.HTTP_401_UNAUTHORIZED
    assert seen_429, "expected a 429 within the attempt budget"
