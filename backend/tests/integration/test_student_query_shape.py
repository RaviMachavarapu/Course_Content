"""Hot student endpoints don't load every historical version's content
(review 2026-10-28): the catalog and /me/listening read only the published
version's audio duration, and /me/listening doesn't do per-row lazy loads."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from tests.integration.test_student_me import _ids, _no_dispatch, _setup

__all__ = ["_no_dispatch"]  # autouse fixture re-exported for this module


@contextmanager
def _statements(db: Session) -> Iterator[list[str]]:
    seen: list[str] = []
    engine = db.get_bind()

    def capture(_conn, _cursor, statement, *_a) -> None:  # type: ignore[no-untyped-def]
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def _version_reads(statements: list[str]) -> list[str]:
    return [s for s in statements if re.search(r"FROM artifact_version\b", s)]


def _assert_only_published_versions(statements: list[str]) -> None:
    for s in _version_reads(statements):
        # a lookup by id (the published version), never "all versions of these
        # artifacts" (selectinload by artifact_id) with their content_json
        assert not re.search(
            r"artifact_version\.artifact_id (IN|=)|= artifact_version\.artifact_id", s
        ), s


def test_catalog_reads_only_published_versions(client: TestClient, db_session: Session) -> None:
    _setup(client, db_session)
    with _statements(db_session) as seen:
        r = client.get("/api/student/courses")
    assert r.status_code == 200
    assert r.json()["courses"][0]["total_audio_seconds"]  # still computed
    _assert_only_published_versions(seen)


def test_listening_reads_only_published_versions_without_n_plus_1(
    client: TestClient, db_session: Session
) -> None:
    slug, _ = _setup(client, db_session)
    ids = _ids(client, slug)
    client.put(
        f"/api/student/artifacts/{ids['audio_overview']}/progress",
        json={"audio_position_seconds": 5},
    )
    db_session.expire_all()
    with _statements(db_session) as seen:
        rows = client.get("/api/student/me/listening").json()["rows"]
    assert len(rows) == 1 and rows[0]["duration_seconds"] > 0
    _assert_only_published_versions(seen)
    # the audio artifacts it loads are only the ones this student opened
    assert any("JOIN artifact_progress" in s for s in seen)
    # and the row's course/module tree is eager-loaded: a fixed handful of
    # statements (auth + one per relationship level), not one per row
    assert len(seen) <= 10, len(seen)


def test_admin_staging_poll_reads_current_versions_and_latest_jobs_in_bulk(
    client: TestClient, db_session: Session
) -> None:
    """Staging is polled every 2-3 s: not one job query per artifact, and not
    every historical version's content."""
    from tests.integration.test_jobs_api import _admin, _generated_module

    module = _generated_module(db_session)
    _admin(client, db_session)
    db_session.expire_all()
    with _statements(db_session) as seen:
        r = client.get(f"/api/admin/modules/{module.id}/staging")
    assert r.status_code == 200
    arts = r.json()["artifacts"]
    generated = [a for a in arts if a["current_version"]]
    assert len(generated) == 4
    assert all(a["job"]["state"] == "succeeded" for a in generated)
    _assert_only_published_versions(seen)
    assert len([s for s in seen if re.search(r"FROM generation_job\b", s)]) == 1
