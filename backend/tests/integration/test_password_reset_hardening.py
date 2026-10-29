"""Password reset revokes sessions and keeps only one live token (review 2026-10-28)."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator

import pytest
import redis
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password_reset import consume_reset_token, issue_reset_token
from app.cli import seed_admin
from app.config import Settings, get_settings
from app.models.user import User

PW = "old-strong-pw-1"


def _register(client: TestClient, email: str) -> uuid.UUID:
    r = client.post(
        "/api/student/auth/register", json={"email": email, "password": PW, "display_name": "R"}
    )
    assert r.status_code == status.HTTP_201_CREATED
    return uuid.UUID(r.json()["user"]["id"])


def _confirm(client: TestClient, token: str, scope: str = "student") -> int:
    return client.post(
        f"/api/{scope}/auth/password-reset/confirm",
        json={"token": token, "password": "brand-new-pw-2"},
    ).status_code


def test_reset_revokes_every_existing_session(
    client: TestClient, redis_client: redis.Redis[str]
) -> None:
    uid = _register(client, "victim@example.com")
    stolen = dict(client.cookies)  # e.g. a stolen cookie on another machine
    attacker = TestClient(client.app, cookies=stolen)
    assert attacker.get("/api/student/auth/me").status_code == status.HTTP_200_OK

    token = issue_reset_token(redis_client, user_id=uid, scope="student")
    assert _confirm(TestClient(client.app), token) == status.HTTP_204_NO_CONTENT

    assert attacker.get("/api/student/auth/me").status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get("/api/student/auth/me").status_code == status.HTTP_401_UNAUTHORIZED

    # a fresh login after the reset works
    fresh = TestClient(client.app)
    r = fresh.post(
        "/api/student/auth/login",
        json={"email": "victim@example.com", "password": "brand-new-pw-2"},
    )
    assert r.status_code == status.HTTP_200_OK
    assert fresh.get("/api/student/auth/me").status_code == status.HTTP_200_OK


def test_admin_reset_revokes_admin_sessions(
    client: TestClient, db_session: Session, redis_client: redis.Redis[str]
) -> None:
    seed_admin(db_session, email="boss@example.com", display_name="B", password="admin-pw-12345")
    db_session.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "boss@example.com", "password": "admin-pw-12345"}
    )
    assert client.get("/api/admin/auth/me").status_code == status.HTTP_200_OK
    admin_id = db_session.scalar(select(User.id).where(User.email == "boss@example.com"))
    assert admin_id is not None
    token = issue_reset_token(redis_client, user_id=admin_id, scope="admin")
    assert _confirm(TestClient(client.app), token, "admin") == status.HTTP_204_NO_CONTENT
    assert client.get("/api/admin/auth/me").status_code == status.HTTP_401_UNAUTHORIZED


def test_a_new_request_invalidates_the_previous_token(
    client: TestClient, redis_client: redis.Redis[str]
) -> None:
    uid = _register(client, "twice@example.com")
    first = issue_reset_token(redis_client, user_id=uid, scope="student")
    second = issue_reset_token(redis_client, user_id=uid, scope="student")
    assert _confirm(client, first) == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert _confirm(client, second) == status.HTTP_204_NO_CONTENT


def test_a_used_token_leaves_no_other_token_alive(
    client: TestClient, redis_client: redis.Redis[str]
) -> None:
    uid = _register(client, "single@example.com")
    token = issue_reset_token(redis_client, user_id=uid, scope="student")
    assert _confirm(client, token) == status.HTTP_204_NO_CONTENT
    assert not list(redis_client.scan_iter("pwreset*"))


def test_consume_is_atomic_under_concurrency(redis_client: redis.Redis[str]) -> None:
    uid = uuid.uuid4()
    for _ in range(5):
        token = issue_reset_token(redis_client, user_id=uid, scope="student")
        barrier = threading.Barrier(8)
        wins: list[uuid.UUID] = []

        def go(tok: str = token, b: threading.Barrier = barrier, w: list[uuid.UUID] = wins) -> None:
            b.wait()
            got = consume_reset_token(redis_client, token=tok, scope="student")
            if got is not None:
                w.append(got)

        threads = [threading.Thread(target=go) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert wins == [uid]


@pytest.fixture
def reset_disabled(client: TestClient) -> Iterator[TestClient]:
    settings = Settings(password_reset_enabled=False)
    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    yield client
    client.app.dependency_overrides.pop(get_settings, None)  # type: ignore[attr-defined]


@pytest.mark.parametrize("scope", ["student", "admin"])
def test_reset_can_be_switched_off(
    reset_disabled: TestClient, redis_client: redis.Redis[str], scope: str
) -> None:
    r = reset_disabled.post(
        f"/api/{scope}/auth/password-reset/request", json={"email": "a@example.com"}
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND
    assert r.json()["error"]["code"] == "password_reset_disabled"
    token = issue_reset_token(redis_client, user_id=uuid.uuid4(), scope=scope)  # type: ignore[arg-type]
    assert _confirm(reset_disabled, token, scope) == status.HTTP_404_NOT_FOUND
