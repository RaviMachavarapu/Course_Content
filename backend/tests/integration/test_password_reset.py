"""O6 — tokenised, single-use, 30-minute password reset, for both scopes.

Exercised against the real mailhog inbox (its REST API), not a mocked mailer,
so this proves the actual email gets sent with a working link — not just that
`send_mail` was called.
"""

from __future__ import annotations

import quopri
import re
import uuid

import httpx
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin

_MAILHOG = "http://mailhog:8025"
_TOKEN_RE = re.compile(r"[?&]token=([\w-]+)")


@pytest.fixture(autouse=True)
def _clear_mailhog() -> None:
    httpx.delete(f"{_MAILHOG}/api/v1/messages", timeout=5)
    yield
    httpx.delete(f"{_MAILHOG}/api/v1/messages", timeout=5)


def _latest_email_to(address: str) -> dict:
    for _ in range(20):
        data = httpx.get(f"{_MAILHOG}/api/v2/messages", timeout=5).json()
        for item in data.get("items", []):
            to = item["Content"]["Headers"].get("To", [])
            if any(address in t for t in to):
                return item
        __import__("time").sleep(0.25)
    raise AssertionError(f"no email arrived for {address}")


def _decoded_body(email: dict) -> str:
    # mailhog's API returns the raw MIME part body — decode the
    # quoted-printable transfer encoding (soft line-wraps + "=" escaping)
    # the same way any real mail client would before rendering it.
    return quopri.decodestring(email["Content"]["Body"].encode()).decode()


def _extract_token(email: dict) -> str:
    body = _decoded_body(email)
    match = _TOKEN_RE.search(body)
    assert match, f"no reset token found in email body: {body!r}"
    return match.group(1)


def test_student_password_reset_end_to_end(client: TestClient) -> None:
    email = f"reset-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/student/auth/register",
        json={"email": email, "password": "old-strong-pw-1", "display_name": "R"},
    )
    client.cookies.clear()

    resp = client.post("/api/student/auth/password-reset/request", json={"email": email})
    assert resp.status_code == status.HTTP_202_ACCEPTED

    sent = _latest_email_to(email)
    token = _extract_token(sent)

    confirm = client.post(
        "/api/student/auth/password-reset/confirm",
        json={"token": token, "password": "brand-new-pw-2"},
    )
    assert confirm.status_code == status.HTTP_204_NO_CONTENT

    old_login = client.post(
        "/api/student/auth/login", json={"email": email, "password": "old-strong-pw-1"}
    )
    assert old_login.status_code == status.HTTP_401_UNAUTHORIZED

    new_login = client.post(
        "/api/student/auth/login", json={"email": email, "password": "brand-new-pw-2"}
    )
    assert new_login.status_code == status.HTTP_200_OK


def test_admin_password_reset_end_to_end(client: TestClient, db_session: Session) -> None:
    email = f"reset-admin-{uuid.uuid4().hex[:8]}@example.com"
    seed_admin(db_session, email=email, display_name="Reset Admin", password="old-admin-pw-1")
    db_session.flush()

    resp = client.post("/api/admin/auth/password-reset/request", json={"email": email})
    assert resp.status_code == status.HTTP_202_ACCEPTED

    sent = _latest_email_to(email)
    token = _extract_token(sent)
    assert "/admin/reset-password" in _decoded_body(sent)

    confirm = client.post(
        "/api/admin/auth/password-reset/confirm",
        json={"token": token, "password": "brand-new-admin-pw-2"},
    )
    assert confirm.status_code == status.HTTP_204_NO_CONTENT

    new_login = client.post(
        "/api/admin/auth/login", json={"email": email, "password": "brand-new-admin-pw-2"}
    )
    assert new_login.status_code == status.HTTP_200_OK


def test_request_for_unknown_email_sends_nothing_and_still_202(client: TestClient) -> None:
    resp = client.post(
        "/api/student/auth/password-reset/request",
        json={"email": "no-such-account@example.com"},
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED

    messages = httpx.get(f"{_MAILHOG}/api/v2/messages", timeout=5).json()
    assert messages["total"] == 0


def test_reset_rejects_wrong_scope_and_bogus_tokens(client: TestClient) -> None:
    student_email = f"cross-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/student/auth/register",
        json={"email": student_email, "password": "old-strong-pw-1", "display_name": "C"},
    )
    client.post("/api/student/auth/password-reset/request", json={"email": student_email})
    token = _extract_token(_latest_email_to(student_email))

    # an admin-scope confirm must not accept a student-scope token
    cross_scope = client.post(
        "/api/admin/auth/password-reset/confirm",
        json={"token": token, "password": "brand-new-pw-2"},
    )
    assert cross_scope.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert cross_scope.json()["error"]["code"] == "invalid_token"

    # a token that never existed is rejected the same way
    bogus = client.post(
        "/api/student/auth/password-reset/confirm",
        json={"token": "not-a-real-token", "password": "brand-new-pw-2"},
    )
    assert bogus.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_reset_token_can_never_be_replayed(client: TestClient) -> None:
    email = f"replay-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/student/auth/register",
        json={"email": email, "password": "old-strong-pw-1", "display_name": "P"},
    )
    client.post("/api/student/auth/password-reset/request", json={"email": email})
    token = _extract_token(_latest_email_to(email))

    first = client.post(
        "/api/student/auth/password-reset/confirm",
        json={"token": token, "password": "brand-new-pw-2"},
    )
    assert first.status_code == status.HTTP_204_NO_CONTENT

    second = client.post(
        "/api/student/auth/password-reset/confirm",
        json={"token": token, "password": "another-pw-3"},
    )
    assert second.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_confirm_rejects_a_weak_new_password(client: TestClient) -> None:
    email = f"weak-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/student/auth/register",
        json={"email": email, "password": "old-strong-pw-1", "display_name": "W"},
    )
    client.post("/api/student/auth/password-reset/request", json={"email": email})
    token = _extract_token(_latest_email_to(email))

    resp = client.post(
        "/api/student/auth/password-reset/confirm", json={"token": token, "password": "short"}
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert resp.json()["error"]["code"] == "weak_password"
