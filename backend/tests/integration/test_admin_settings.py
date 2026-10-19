"""T029 — Settings (A4): admin users + audio defaults."""

from __future__ import annotations

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin


def _login(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="root@example.com", display_name="Root", password="root-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login",
        json={"email": "root@example.com", "password": "root-admin-pw-1"},
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def test_list_contains_seeded_admin(client: TestClient, db_session: Session) -> None:
    h = _login(client, db_session)
    users = client.get("/api/admin/users", headers=h).json()["users"]
    assert any(u["email"] == "root@example.com" and u["is_active"] for u in users)


def test_create_admin_then_it_can_log_in(client: TestClient, db_session: Session) -> None:
    h = _login(client, db_session)
    resp = client.post(
        "/api/admin/users",
        json={
            "email": "New@Example.com",
            "display_name": "New Admin",
            "password": "brand-new-pw-9",
        },
        headers=h,
    )
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.json()["email"] == "new@example.com"

    client.cookies.clear()
    login = client.post(
        "/api/admin/auth/login",
        json={"email": "new@example.com", "password": "brand-new-pw-9"},
    )
    assert login.status_code == status.HTTP_200_OK


def test_create_admin_rejects_weak_password_and_duplicate(
    client: TestClient, db_session: Session
) -> None:
    h = _login(client, db_session)
    weak = client.post(
        "/api/admin/users",
        json={"email": "a@example.com", "display_name": "A", "password": "short"},
        headers=h,
    )
    assert weak.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert weak.json()["error"]["code"] == "weak_password"

    dup = client.post(
        "/api/admin/users",
        json={"email": "root@example.com", "display_name": "R", "password": "another-good-pw-2"},
        headers=h,
    )
    assert dup.status_code == status.HTTP_409_CONFLICT
    assert dup.json()["error"]["code"] == "email_taken"


def test_deactivate_other_admin_but_not_self(client: TestClient, db_session: Session) -> None:
    h = _login(client, db_session)
    me = client.get("/api/admin/auth/me", headers=h).json()["user"]
    other_id = client.post(
        "/api/admin/users",
        json={"email": "other@example.com", "display_name": "Other", "password": "other-good-pw-3"},
        headers=h,
    ).json()["id"]

    ok = client.patch(f"/api/admin/users/{other_id}", json={"is_active": False}, headers=h)
    assert ok.status_code == status.HTTP_200_OK
    assert ok.json()["is_active"] is False

    reactivate = client.patch(f"/api/admin/users/{other_id}", json={"is_active": True}, headers=h)
    assert reactivate.json()["is_active"] is True

    self_off = client.patch(f"/api/admin/users/{me['id']}", json={"is_active": False}, headers=h)
    assert self_off.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert self_off.json()["error"]["code"] == "cannot_deactivate_self"


def test_deactivating_an_admin_immediately_revokes_their_live_session(
    client: TestClient, db_session: Session
) -> None:
    root_h = _login(client, db_session)
    other_id = client.post(
        "/api/admin/users",
        json={"email": "live@example.com", "display_name": "Live", "password": "live-good-pw-4"},
        headers=root_h,
    ).json()["id"]
    root_cookies = dict(client.cookies)

    # "other" logs in for real, holding their own live session + CSRF token
    client.cookies.clear()
    client.post(
        "/api/admin/auth/login", json={"email": "live@example.com", "password": "live-good-pw-4"}
    )
    other_cookies = dict(client.cookies)
    other_h = {"X-CSRF-Token": other_cookies["sdp_csrf"]}
    assert client.get("/api/admin/auth/me", headers=other_h).status_code == status.HTTP_200_OK

    # root deactivates them while that session is still live
    client.cookies.clear()
    client.cookies.update(root_cookies)
    deactivate = client.patch(
        f"/api/admin/users/{other_id}", json={"is_active": False}, headers=root_h
    )
    assert deactivate.status_code == status.HTTP_200_OK

    # the already-issued session is rejected on its very next request
    client.cookies.clear()
    client.cookies.update(other_cookies)
    resp = client.get("/api/admin/auth/me", headers=other_h)
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


def test_audio_settings_default_then_persist_and_normalize(
    client: TestClient, db_session: Session
) -> None:
    h = _login(client, db_session)
    got = client.get("/api/admin/settings/audio", headers=h).json()
    assert got["settings"] == {"voice": "default", "style": "conversational"}
    assert "warm" in got["voice_choices"]

    saved = client.put(
        "/api/admin/settings/audio",
        json={"voice": "warm", "style": "not-a-real-style"},
        headers=h,
    ).json()
    assert saved["settings"] == {"voice": "warm", "style": "conversational"}  # style normalized

    # persisted across a fresh GET
    again = client.get("/api/admin/settings/audio", headers=h).json()
    assert again["settings"] == {"voice": "warm", "style": "conversational"}


def test_settings_endpoints_require_admin(client: TestClient, db_session: Session) -> None:
    _login(client, db_session)
    client.cookies.clear()
    assert client.get("/api/admin/users").status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get("/api/admin/settings/audio").status_code == status.HTTP_401_UNAUTHORIZED
