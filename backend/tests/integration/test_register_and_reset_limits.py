"""Unauthenticated register / reset-request: rate limits, constant responses,
Argon2 concurrency cap, register race (review 2026-10-28)."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.student import auth as student_auth
from app.auth import hashing, password_reset
from app.config import Settings, get_settings
from app.models.user import User

PW = "strong-pass-123"


@pytest.fixture
def tight(client: TestClient) -> Iterator[TestClient]:
    settings = Settings(register_rate_limit="3/1h", password_reset_rate_limit="3/1h")
    client.app.dependency_overrides[get_settings] = lambda: settings  # type: ignore[attr-defined]
    yield client
    client.app.dependency_overrides.pop(get_settings, None)  # type: ignore[attr-defined]


def _register(client: TestClient, email: str, **over: object) -> object:
    return client.post(
        "/api/student/auth/register",
        json={"email": email, "password": PW, "display_name": "N", **over},
    )


def test_register_is_rate_limited_per_ip(tight: TestClient) -> None:
    codes = [_register(tight, f"r{i}@example.com").status_code for i in range(4)]  # type: ignore[attr-defined]
    assert codes[:3] == [status.HTTP_201_CREATED] * 3
    assert codes[3] == status.HTTP_429_TOO_MANY_REQUESTS
    other = TestClient(tight.app, client=("10.2.2.2", 50000))
    assert _register(other, "r9@example.com").status_code == status.HTTP_201_CREATED  # type: ignore[attr-defined]


def test_register_rejects_a_blank_display_name(client: TestClient) -> None:
    r = _register(client, "blank@example.com", display_name="   ")
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY  # type: ignore[attr-defined]


def test_register_race_is_409_not_500(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two registers of the same email both pass the existence check; the loser
    hits the unique index and must get 409 email_taken (session still usable)."""
    from app.models.user import UserRole

    def sneak_in(*_a: object, **_k: object) -> int:
        # the other request commits between our check and our insert
        with db_session.begin_nested():
            db_session.add(
                User(
                    email="race@example.com",
                    password_hash="x",
                    role=UserRole.student,
                    display_name="Other",
                )
            )
        return 0

    monkeypatch.setattr(student_auth, "_email_taken", sneak_in)
    r = _register(client, "race@example.com")
    assert r.status_code == status.HTTP_409_CONFLICT  # type: ignore[attr-defined]
    assert r.json()["error"]["code"] == "email_taken"  # type: ignore[attr-defined]
    assert db_session.scalar(select(User.display_name).where(User.email == "race@example.com")) == (
        "Other"
    )


def test_reset_request_is_rate_limited_per_ip(tight: TestClient) -> None:
    codes = [
        tight.post(
            "/api/student/auth/password-reset/request", json={"email": f"n{i}@example.com"}
        ).status_code
        for i in range(4)
    ]
    assert codes[:3] == [status.HTTP_202_ACCEPTED] * 3
    assert codes[3] == status.HTTP_429_TOO_MANY_REQUESTS


def test_reset_request_per_email_cap_is_silent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mail-bombing one inbox from many IPs: past the per-email cap the
    response is still 202, but no more mail is sent."""
    sent: list[str] = []
    monkeypatch.setattr(password_reset, "send_mail", lambda _s, *, to, **_k: sent.append(to))
    _register(client, "inbox@example.com")
    for i in range(6):
        c = TestClient(client.app, client=(f"10.3.3.{i}", 50000))
        r = c.post("/api/student/auth/password-reset/request", json={"email": "inbox@example.com"})
        assert r.status_code == status.HTTP_202_ACCEPTED
    assert len(sent) == password_reset.PER_EMAIL_REQUESTS_PER_HOUR


def test_reset_request_mail_failure_is_not_a_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SMTP down must look exactly like "no such account": 202, empty body."""

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("smtp down")

    monkeypatch.setattr("app.services.mail._deliver", boom)
    _register(client, "real@example.com")
    client.cookies.clear()
    real = client.post(
        "/api/student/auth/password-reset/request", json={"email": "real@example.com"}
    )
    fake = client.post(
        "/api/student/auth/password-reset/request", json={"email": "fake@example.com"}
    )
    assert real.status_code == fake.status_code == status.HTTP_202_ACCEPTED
    assert real.content == fake.content


def test_reset_mail_is_sent_off_the_request_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow SMTP relay doesn't slow the response (it runs as a background task,
    after the response is sent)."""
    order: list[str] = []

    def slow(*_a: object, **_k: object) -> None:
        order.append("mail")

    monkeypatch.setattr(password_reset, "send_mail", slow)
    _register(client, "slow@example.com")
    from starlette.background import BackgroundTasks

    real_add = BackgroundTasks.add_task

    def spy(self: BackgroundTasks, func: object, *a: object, **k: object) -> None:
        order.append("scheduled")
        real_add(self, func, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(BackgroundTasks, "add_task", spy)
    r = client.post("/api/student/auth/password-reset/request", json={"email": "slow@example.com"})
    assert r.status_code == status.HTTP_202_ACCEPTED
    assert order == ["scheduled", "mail"]


def test_argon2_work_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each Argon2 hash takes ~64 MiB; concurrent ones are capped so a burst of
    anonymous registers can't exhaust the container's memory."""
    live = 0
    peak = 0
    lock = threading.Lock()

    class SlowHasher:
        def hash(self, _pw: str) -> str:
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(0.05)
            with lock:
                live -= 1
            return "h"

    monkeypatch.setattr(hashing, "_hasher", SlowHasher())
    threads = [threading.Thread(target=hashing.hash_password, args=("pw",)) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert 1 <= peak <= hashing.MAX_CONCURRENT_HASHES
