"""Session lifetime (owner decision 3, 2026-10-29).

Admin: renews while active, 8 h idle timeout, absolute maximum 7 days.
Student: unchanged — 30 days idle, ended 30 days after sign-in at the latest
(before, the cookie's fixed 30-day max-age did that; now the server does too).
Renewal doesn't write on every request: only once less than half the idle
window is left.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.sessions import SessionStore
from app.cli import seed_admin
from app.config import get_settings

ADMIN_PW = "admin-pw-12345"
STUDENT = {"email": "s@example.com", "password": "sup3r-secret-pw", "display_name": "S"}
HOUR = 3600
DAY = 86400


def _admin(client: TestClient, db: Session) -> Any:
    seed_admin(db, email="boss@example.com", display_name="B", password=ADMIN_PW)
    db.flush()
    r = client.post(
        "/api/admin/auth/login",
        json={"email": "boss@example.com", "password": ADMIN_PW, "remember": True},
    )
    assert r.status_code == status.HTTP_200_OK
    return r


def _key(scope: str, client: TestClient) -> str:
    return f"sess:{scope}:{client.cookies.get(f'sdp_{scope}')}"


def _age_session(redis_client: Any, key: str, seconds: float) -> None:
    """Pretend the session was created `seconds` ago."""
    data = json.loads(redis_client.get(key))
    created = dt.datetime.now(tz=dt.UTC) - dt.timedelta(seconds=seconds)
    data["created_at"] = created.isoformat()
    redis_client.set(key, json.dumps(data), keepttl=True)


def _cookie_max_age(response: Any, name: str) -> int:
    header = next(h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}="))
    part = next(p for p in header.split(";") if p.strip().lower().startswith("max-age="))
    return int(part.split("=", 1)[1])


def test_defaults() -> None:
    s = get_settings()
    assert s.admin_session_ttl_hours == 8
    assert s.admin_session_max_days == 7
    assert s.student_session_ttl_days == 30
    assert s.student_session_max_days == 30


def test_admin_session_starts_with_the_idle_window_and_a_7_day_cookie(
    client: TestClient, db_session: Session, redis_client: Any
) -> None:
    r = _admin(client, db_session)
    assert _cookie_max_age(r, "sdp_admin") == 7 * DAY
    ttl = redis_client.ttl(_key("admin", client))
    assert 8 * HOUR - 5 <= ttl <= 8 * HOUR


def test_student_cookie_keeps_its_30_day_lifetime(client: TestClient) -> None:
    r = client.post("/api/student/auth/register", json=STUDENT)
    assert _cookie_max_age(r, "sdp_student") == 30 * DAY


def test_an_active_admin_session_is_renewed(
    client: TestClient, db_session: Session, redis_client: Any
) -> None:
    _admin(client, db_session)
    key = _key("admin", client)
    redis_client.expire(key, 3 * HOUR)  # less than half of 8 h left
    assert client.get("/api/admin/auth/me").status_code == status.HTTP_200_OK
    assert redis_client.ttl(key) > 7 * HOUR


def test_no_renewal_write_while_more_than_half_is_left(
    client: TestClient, db_session: Session, redis_client: Any
) -> None:
    _admin(client, db_session)
    key = _key("admin", client)
    redis_client.expire(key, 5 * HOUR)
    assert client.get("/api/admin/auth/me").status_code == status.HTTP_200_OK
    assert redis_client.ttl(key) <= 5 * HOUR


def test_an_idle_admin_session_ends(
    client: TestClient, db_session: Session, redis_client: Any
) -> None:
    _admin(client, db_session)
    redis_client.delete(_key("admin", client))  # what the 8 h TTL does
    r = client.get("/api/admin/users")
    assert r.status_code == status.HTTP_401_UNAUTHORIZED


def test_admin_session_ends_after_7_days_however_active(
    client: TestClient, db_session: Session, redis_client: Any
) -> None:
    _admin(client, db_session)
    key = _key("admin", client)
    _age_session(redis_client, key, 7 * DAY + 1)
    assert client.get("/api/admin/auth/me").status_code == status.HTTP_401_UNAUTHORIZED
    assert redis_client.get(key) is None


def test_renewal_never_passes_the_absolute_maximum(
    client: TestClient, db_session: Session, redis_client: Any
) -> None:
    _admin(client, db_session)
    key = _key("admin", client)
    _age_session(redis_client, key, 7 * DAY - HOUR)  # one hour of its life left
    redis_client.expire(key, 30 * 60)
    assert client.get("/api/admin/auth/me").status_code == status.HTTP_200_OK
    assert 30 * 60 < redis_client.ttl(key) <= HOUR


def test_student_session_renews_and_ends_after_30_days(
    client: TestClient, redis_client: Any
) -> None:
    assert client.post("/api/student/auth/register", json=STUDENT).status_code == 201
    key = _key("student", client)
    redis_client.expire(key, 10 * DAY)
    assert client.get("/api/student/auth/me").status_code == status.HTTP_200_OK
    assert redis_client.ttl(key) > 29 * DAY
    _age_session(redis_client, key, 30 * DAY + 1)
    assert client.get("/api/student/auth/me").status_code == status.HTTP_401_UNAUTHORIZED


def test_old_sessions_without_the_new_fields_still_work(redis_client: Any) -> None:
    store = SessionStore(redis_client, get_settings())
    created = dt.datetime.now(tz=dt.UTC).isoformat()
    redis_client.setex(
        "sess:admin:legacy",
        HOUR,
        json.dumps({"user_id": "u", "scope": "admin", "created_at": created}),
    )
    session = store.read("admin", "legacy")
    assert session is not None
    assert session.remember is True
