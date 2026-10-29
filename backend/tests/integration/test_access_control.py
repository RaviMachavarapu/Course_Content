"""T040 — access-control audit (US-N1..N4).

US-N1 (student/anon blocked from every /api/admin/*) already has thorough,
dynamically-generated coverage in `test_rbac.py` — every admin route is
enumerated from the live FastAPI app, so newly added admin endpoints are
covered automatically. This file covers the rest of the audit:

  N2 — an unpublished artifact / its media is never served to a student or an
       anonymous caller (also: every /api/student/* route, dynamically swept,
       rejects anonymous requests).
  N3 — see also `frontend/src/app/adminBoundary.test.ts` (build-time: nothing
       under src/student imports admin code).
  N4 — a redo, or a failed regeneration, never touches the currently published
       version until the operator explicitly republishes.

Media hostile-key handling (path traversal, unknown keys) is covered in
`test_media.py::test_bad_and_unknown_keys_are_404`.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest
from fastapi import status
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin
from app.main import create_app
from app.models.artifact import Artifact
from app.models.enums import ArtifactStatus, ArtifactType
from app.models.module import Module
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider
from app.render import RenderError
from app.storage.service import Storage

PROVIDER = FixtureProvider()

# these exist before any session, or don't gate on one (pre-auth, like admin's
# login/logout in test_rbac.py)
_PRE_AUTH = {
    ("/api/student/auth/register", "POST"),
    ("/api/student/auth/login", "POST"),
    ("/api/student/auth/logout", "POST"),
    # password reset (O6) is deliberately public — you're logged out when using it
    ("/api/student/auth/password-reset/request", "POST"),
    ("/api/student/auth/password-reset/confirm", "POST"),
}


def _guarded_student_routes() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for route in create_app().routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/student/"):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if (route.path, method) not in _PRE_AUTH:
                out.append((route.path, method))
    return out


STUDENT_ROUTES = _guarded_student_routes()


@pytest.mark.parametrize(("path", "method"), STUDENT_ROUTES)
def test_student_routes_reject_anonymous(client: TestClient, path: str, method: str) -> None:
    resp = client.request(method, path, json={} if method in ("POST", "PUT") else None)
    assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.parametrize(("path", "method"), STUDENT_ROUTES)
def test_student_routes_reject_admin_session(
    client: TestClient, db_session: Session, path: str, method: str
) -> None:
    seed_admin(db_session, email="n2@example.com", display_name="N2", password="n2-admin-pw-1")
    db_session.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "n2@example.com", "password": "n2-admin-pw-1"}
    )
    headers = {"X-CSRF-Token": client.cookies.get("sdp_csrf", "")}
    resp = client.request(
        method, path, headers=headers, json={} if method in ("POST", "PUT") else None
    )
    assert resp.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


def _admin_headers(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="ac-admin@example.com", display_name="A", password="ac-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "ac-admin@example.com", "password": "ac-admin-pw-1"}
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def _module_with_one_artifact(
    client: TestClient, db: Session, h: dict[str, str], title: str
) -> Module:
    cid = client.post("/api/admin/courses", json={"title": title}, headers=h).json()["course"]["id"]
    mid = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={"source_url": f"https://example.com/{title}", "title": title, "types": ["report"]},
        headers=h,
    ).json()["module"]["id"]
    module = db.get(Module, uuid.UUID(mid))
    assert module is not None
    return module


def test_unpublished_artifact_is_404_for_student_and_401_for_anonymous(
    client: TestClient, db_session: Session
) -> None:
    h = _admin_headers(client, db_session)
    module = _module_with_one_artifact(client, db_session, h, "N2 Unpublished")
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    # generated but never published
    orchestrator.run_artifact_generation(db_session, PROVIDER, report.id)
    db_session.flush()

    # anonymous: not authenticated at all
    assert (
        client.get(f"/api/student/artifacts/{report.id}").status_code
        == status.HTTP_401_UNAUTHORIZED
    )

    # a real student session: 404, never a peek at the content or a 403 that
    # would confirm the artifact exists
    client.post(
        "/api/student/auth/register",
        json={"email": "n2b@example.com", "password": "n2-student-pw-1", "display_name": "S"},
    )
    resp = client.get(f"/api/student/artifacts/{report.id}")
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert "content_json" not in resp.json()


def test_redo_never_touches_the_published_version(client: TestClient, db_session: Session) -> None:
    h = _admin_headers(client, db_session)
    module = _module_with_one_artifact(client, db_session, h, "N4 Redo")
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)

    orchestrator.run_artifact_generation(db_session, PROVIDER, report.id)
    db_session.expire_all()
    report = db_session.get(Artifact, report.id)
    assert report is not None
    report.published_version_id = report.current_version_id
    report.status = ArtifactStatus.published
    published_id = report.published_version_id
    db_session.flush()

    # a redo produces a new version but must not move published_version_id
    orchestrator.run_artifact_generation(
        db_session, PROVIDER, report.id, redo_note="make it shorter"
    )
    db_session.expire_all()
    report = db_session.get(Artifact, report.id)
    assert report is not None
    assert report.published_version_id == published_id
    assert report.current_version_id != published_id


def test_failed_regeneration_never_touches_the_published_version(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _admin_headers(client, db_session)
    module = _module_with_one_artifact(client, db_session, h, "N4 Failure")
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)

    orchestrator.run_artifact_generation(db_session, PROVIDER, report.id)
    db_session.expire_all()
    report = db_session.get(Artifact, report.id)
    assert report is not None
    report.published_version_id = report.current_version_id
    report.status = ArtifactStatus.published
    published_id = report.published_version_id
    db_session.flush()

    def _boom(*_a: object, **_k: object) -> None:
        raise RenderError("simulated render failure")

    from app.pipeline.orchestrator import RENDERERS as live_renderers

    monkeypatch.setattr(
        "app.pipeline.orchestrator.RENDERERS",
        {**live_renderers, ArtifactType.report: _boom},
    )
    with contextlib.suppress(RenderError):
        orchestrator.run_artifact_generation(
            db_session, PROVIDER, report.id, redo_note="trigger a failure"
        )

    db_session.expire_all()
    report = db_session.get(Artifact, report.id)
    assert report is not None
    assert report.status is ArtifactStatus.error
    # the published version is untouched — students still see the last-good content
    assert report.published_version_id == published_id
    published_version = next(v for v in report.versions if v.id == published_id)
    assert published_version.content_json is not None


def test_student_cannot_fetch_module_pdf(
    client: TestClient, db_session: Session, media_storage: Storage
) -> None:
    import io

    from pypdf import PdfWriter

    h = _admin_headers(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "pdfc"}, headers=h).json()["course"][
        "id"
    ]
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    w.write(buf)
    data = buf.getvalue()
    uid = client.post(
        "/api/admin/uploads", json={"file_name": "s.pdf", "size_bytes": len(data)}, headers=h
    ).json()["upload_id"]
    client.put(
        f"/api/admin/uploads/{uid}?offset=0",
        content=data,
        headers={**h, "Content-Type": "application/octet-stream"},
    )
    mod = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={"title": "m", "types": ["report"], "upload_ids": [uid]},
        headers=h,
    ).json()["module"]
    m = db_session.get(Module, uuid.UUID(mod["id"]))
    assert m is not None
    key = m.source_files[0].storage_key

    # no MediaFile row exists for a module PDF, so /api/media never serves it
    assert media_storage.exists(key)
    client.cookies.clear()
    # anonymous: the media route requires a session (401), as for any media key
    assert client.get(f"/api/media/{key}").status_code == status.HTTP_401_UNAUTHORIZED
    client.post(
        "/api/student/auth/register",
        json={"email": "pdf-s@example.com", "password": "n2-student-pw-1", "display_name": "S"},
    )
    assert client.get(f"/api/media/{key}").status_code == status.HTTP_404_NOT_FOUND
