"""Chunked, resumable admin PDF uploads."""

from __future__ import annotations

import datetime as dt
import uuid
from contextlib import contextmanager

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.models.enums import SourceUploadStatus
from app.models.source_upload import SourceUpload
from app.storage.service import Storage

PDF = b"%PDF-1.4\n" + b"x" * 100


def _login(client: TestClient, db: Session, email: str = "u@example.com") -> dict[str, str]:
    seed_admin(db, email=email, display_name="U", password="upload-admin-pw-1")
    db.flush()
    client.post("/api/admin/auth/login", json={"email": email, "password": "upload-admin-pw-1"})
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def _create(client: TestClient, h: dict[str, str], size: int, name: str = "a.pdf") -> str:
    r = client.post("/api/admin/uploads", json={"file_name": name, "size_bytes": size}, headers=h)
    assert r.status_code == status.HTTP_201_CREATED
    assert r.json()["chunk_size"] == 8388608
    return r.json()["upload_id"]


def _put(client: TestClient, h: dict[str, str], uid: str, offset: int, data: bytes):  # type: ignore[no-untyped-def]
    return client.put(
        f"/api/admin/uploads/{uid}?offset={offset}",
        content=data,
        headers={**h, "Content-Type": "application/octet-stream"},
    )


def test_upload_in_chunks_completes(
    client: TestClient, db_session: Session, media_storage: Storage
) -> None:
    h = _login(client, db_session)
    uid = _create(client, h, len(PDF))
    assert _put(client, h, uid, 0, PDF[:50]).json() == {"received_bytes": 50}
    r = _put(client, h, uid, 50, PDF[50:])
    assert r.status_code == 200
    assert r.json() == {"received_bytes": len(PDF)}
    assert client.get(f"/api/admin/uploads/{uid}").json() == {
        "received_bytes": len(PDF),
        "status": "complete",
    }
    row = db_session.get(SourceUpload, uuid.UUID(uid))
    assert row is not None
    assert media_storage.open(row.storage_key) == PDF


def test_put_wrong_offset_conflict(client: TestClient, db_session: Session) -> None:
    h = _login(client, db_session)
    uid = _create(client, h, len(PDF))
    _put(client, h, uid, 0, PDF[:50])
    r = _put(client, h, uid, 10, PDF[10:60])
    assert r.status_code == status.HTTP_409_CONFLICT
    assert r.json()["code"] == "offset_mismatch"
    assert r.json()["received_bytes"] == 50


def test_put_recovers_when_file_is_ahead_of_db(
    client: TestClient, db_session: Session, media_storage: Storage
) -> None:
    h = _login(client, db_session)
    uid = _create(client, h, len(PDF))
    _put(client, h, uid, 0, PDF[:30])
    row = db_session.get(SourceUpload, uuid.UUID(uid))
    assert row is not None
    # simulate a write that reached disk but never committed
    media_storage.append(row.storage_key, 30, b"garbage-tail")
    r = _put(client, h, uid, 30, PDF[30:])
    assert r.status_code == 200
    assert r.json() == {"received_bytes": len(PDF)}
    assert media_storage.open(row.storage_key) == PDF


def test_duplicate_chunk_conflicts_and_file_intact(
    client: TestClient, db_session: Session, media_storage: Storage
) -> None:
    h = _login(client, db_session)
    uid = _create(client, h, len(PDF))
    assert _put(client, h, uid, 0, PDF[:50]).status_code == 200
    r = _put(client, h, uid, 0, PDF[:50])
    assert r.status_code == status.HTTP_409_CONFLICT
    assert r.json()["code"] == "offset_mismatch"
    assert r.json()["received_bytes"] == 50
    row = db_session.get(SourceUpload, uuid.UUID(uid))
    assert row is not None
    assert media_storage.open(row.storage_key) == PDF[:50]


def test_put_requires_csrf(client: TestClient, db_session: Session) -> None:
    h = _login(client, db_session)
    uid = _create(client, h, len(PDF))
    r = client.put(
        f"/api/admin/uploads/{uid}?offset=0",
        content=PDF,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN
    assert client.get(f"/api/admin/uploads/{uid}").json()["received_bytes"] == 0


def test_resume_reports_received_bytes(client: TestClient, db_session: Session) -> None:
    h = _login(client, db_session)
    uid = _create(client, h, len(PDF))
    _put(client, h, uid, 0, PDF[:30])
    assert client.get(f"/api/admin/uploads/{uid}").json() == {
        "received_bytes": 30,
        "status": "receiving",
    }


def test_finished_upload_must_be_pdf(
    client: TestClient, db_session: Session, media_storage: Storage
) -> None:
    h = _login(client, db_session)
    data = b"not a pdf at all"
    uid = _create(client, h, len(data), name="notes.txt.pdf")
    r = _put(client, h, uid, 0, data)
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert r.json()["error"]["code"] == "not_pdf"
    assert r.json()["error"]["message"] == "notes.txt.pdf is not a PDF"
    row = db_session.get(SourceUpload, uuid.UUID(uid))
    assert row is None or not media_storage.exists(row.storage_key)


def test_overrun_is_rejected(client: TestClient, db_session: Session) -> None:
    h = _login(client, db_session)
    uid = _create(client, h, 10)
    r = _put(client, h, uid, 0, b"%PDF-" + b"x" * 20)
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_student_cannot_upload(client: TestClient) -> None:
    client.post(
        "/api/student/auth/register",
        json={"email": "s@example.com", "password": "student-pw-12345", "display_name": "S"},
    )
    h = {"X-CSRF-Token": client.cookies.get("sdp_csrf", "")}
    r = client.post("/api/admin/uploads", json={"file_name": "a.pdf", "size_bytes": 5}, headers=h)
    # student sessions live in a separate scope, so the admin guard answers 401
    # (same as test_rbac); either way the upload is refused
    assert r.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


def test_other_admin_cannot_see_upload(client: TestClient, db_session: Session) -> None:
    h = _login(client, db_session)
    uid = _create(client, h, len(PDF))
    client.post("/api/admin/auth/logout", headers=h)
    h2 = _login(client, db_session, email="other@example.com")
    assert client.get(f"/api/admin/uploads/{uid}").status_code == status.HTTP_404_NOT_FOUND
    assert _put(client, h2, uid, 0, PDF).status_code == status.HTTP_404_NOT_FOUND


def test_purge_deletes_old_unclaimed_only(
    client: TestClient,
    db_session: Session,
    media_storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import maintenance

    h = _login(client, db_session)
    ids = {n: _create(client, h, len(PDF), name=f"{n}.pdf") for n in ("old", "claimed", "recent")}
    for n in ids:
        _put(client, h, ids[n], 0, PDF)
    rows = {n: db_session.get(SourceUpload, uuid.UUID(i)) for n, i in ids.items()}
    old = dt.datetime.now(dt.UTC) - dt.timedelta(hours=25)
    rows["old"].created_at = old  # type: ignore[union-attr]
    rows["claimed"].created_at = old  # type: ignore[union-attr]
    rows["claimed"].status = SourceUploadStatus.claimed  # type: ignore[union-attr]
    db_session.flush()
    keys = {n: r.storage_key for n, r in rows.items()}  # type: ignore[union-attr]

    @contextmanager
    def scope():  # type: ignore[no-untyped-def]
        yield db_session

    monkeypatch.setattr(maintenance, "session_scope", scope)
    monkeypatch.setattr(maintenance, "get_storage", lambda: media_storage)
    assert maintenance.purge_abandoned_uploads() == 1

    assert db_session.get(SourceUpload, uuid.UUID(ids["old"])) is None
    assert not media_storage.exists(keys["old"])
    assert db_session.get(SourceUpload, uuid.UUID(ids["claimed"])) is not None
    assert media_storage.exists(keys["claimed"])
    assert db_session.get(SourceUpload, uuid.UUID(ids["recent"])) is not None
    assert media_storage.exists(keys["recent"])
