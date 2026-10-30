"""Review 2026-10-29: the data migrations against rows that already exist
(scenarios 25 and 26). Each runs on a throwaway database, like
test_db.py::test_migration_backfills_sources_ready_for_existing_notebooks, so
the shared test database stays at head and the dev database is never touched.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.engine import make_url

from app.config import get_settings

T0 = dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.UTC)


@pytest.fixture
def scratch_db() -> Iterator[tuple[AlembicConfig, Engine]]:
    base = make_url(get_settings().database_url)
    name = f"shikshak_test_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(
        base.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    backend = Path(__file__).resolve().parent.parent
    cfg = AlembicConfig(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    engine = create_engine(url)
    try:
        yield cfg, engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _insert(conn: Connection, table: str, **values: object) -> uuid.UUID:
    row_id = uuid.uuid4()
    values = {"id": row_id, **values}
    cols = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    conn.execute(sa.text(f'INSERT INTO "{table}" ({cols}) VALUES ({params})'), values)
    return row_id


def _course(conn: Connection, tag: str) -> uuid.UUID:
    return _insert(
        conn,
        "course",
        title=tag,
        description="d",
        slug=f"{tag}-{uuid.uuid4().hex[:6]}",
        category="cat",
        status="published",
    )


def _module(conn: Connection, course_id: uuid.UUID) -> uuid.UUID:
    return _insert(
        conn,
        "module",
        course_id=course_id,
        order_index=0,
        title="m",
        source_url="https://example.com",
        source_type="web",
        status="published",
    )


def _artifact(
    conn: Connection, module_id: uuid.UUID, *, published: bool, kind: str = "report"
) -> uuid.UUID:
    artifact_id = _insert(
        conn,
        "artifact",
        module_id=module_id,
        type=kind,
        status="published" if published else "ready",
        generation_options="{}",
    )
    version_id = _insert(
        conn, "artifact_version", artifact_id=artifact_id, revision=1, focus_prompt_used=""
    )
    if published:
        conn.execute(
            sa.text("UPDATE artifact SET published_version_id = :v WHERE id = :a"),
            {"v": version_id, "a": artifact_id},
        )
    return artifact_id


def _progress(
    conn: Connection,
    user_id: uuid.UUID,
    artifact_id: uuid.UUID,
    module_id: uuid.UUID,
    completed_at: dt.datetime | None,
) -> None:
    _insert(
        conn,
        "artifact_progress",
        user_id=user_id,
        artifact_id=artifact_id,
        module_id=module_id,
        completed_at=completed_at,
    )


def _course_progress(conn: Connection, user_id: uuid.UUID, course_id: uuid.UUID) -> uuid.UUID:
    return _insert(
        conn, "course_progress", user_id=user_id, course_id=course_id, percent_complete=0
    )


def test_course_complete_backfill_stamps_only_complete_courses(
    scratch_db: tuple[AlembicConfig, Engine],
) -> None:
    """Scenario 25: seeded at a7e3c9d2f480, upgraded to e5c1a9d7b3f2."""
    cfg, engine = scratch_db
    command.upgrade(cfg, "a7e3c9d2f480")
    with engine.begin() as conn:
        user = _insert(
            conn,
            "user",
            email="s@example.com",
            is_active=True,
            display_name="S",
            role="student",
            password_hash="x",
        )
        # complete: both live artifacts done; the stamp is the later completion
        done_course = _course(conn, "done")
        m = _module(conn, done_course)
        a1, a2 = _artifact(conn, m, published=True), _artifact(conn, m, published=True, kind="quiz")
        _progress(conn, user, a1, m, T0)
        _progress(conn, user, a2, m, T0 + dt.timedelta(days=2))
        done = _course_progress(conn, user, done_course)
        # incomplete: one of two live artifacts done
        half_course = _course(conn, "half")
        m = _module(conn, half_course)
        b1, b2 = _artifact(conn, m, published=True), _artifact(conn, m, published=True, kind="quiz")
        _progress(conn, user, b1, m, T0)
        _progress(conn, user, b2, m, None)
        half = _course_progress(conn, user, half_course)
        # no live artifacts at all: never "complete" (no vacuous truth)
        empty_course = _course(conn, "empty")
        m = _module(conn, empty_course)
        c1 = _artifact(conn, m, published=False)
        _progress(conn, user, c1, m, T0)
        empty = _course_progress(conn, user, empty_course)
        # an unpublished (draft) artifact doesn't count against completion
        draft_course = _course(conn, "draft")
        m = _module(conn, draft_course)
        d1, _d2 = (
            _artifact(conn, m, published=True),
            _artifact(conn, m, published=False, kind="quiz"),
        )
        _progress(conn, user, d1, m, T0 + dt.timedelta(days=1))
        with_draft = _course_progress(conn, user, draft_course)

    command.upgrade(cfg, "e5c1a9d7b3f2")

    with engine.connect() as conn:
        stamps: dict[uuid.UUID, dt.datetime | None] = {
            r.id: r.completed_at
            for r in conn.execute(sa.text("SELECT id, completed_at FROM course_progress"))
        }
    assert stamps[done] == T0 + dt.timedelta(days=2)
    assert stamps[half] is None
    assert stamps[empty] is None
    assert stamps[with_draft] == T0 + dt.timedelta(days=1)

    command.downgrade(cfg, "a7e3c9d2f480")
    with engine.connect() as conn:
        cols = {c["name"] for c in sa.inspect(conn).get_columns("course_progress")}
    assert "completed_at" not in cols


def test_one_active_job_per_artifact_migration_cancels_the_older_duplicates(
    scratch_db: tuple[AlembicConfig, Engine],
) -> None:
    """Scenario 26: seeded at c9a4e2b7d613, upgraded to a7e3c9d2f480."""
    cfg, engine = scratch_db
    command.upgrade(cfg, "c9a4e2b7d613")
    with engine.begin() as conn:
        course = _course(conn, "jobs")
        m = _module(conn, course)
        art, other = (
            _artifact(conn, m, published=False),
            _artifact(conn, m, published=False, kind="quiz"),
        )

        def job(artifact_id: uuid.UUID, state: str, minutes: int) -> uuid.UUID:
            return _insert(
                conn,
                "generation_job",
                artifact_id=artifact_id,
                module_id=m,
                kind="generate_artifact",
                state=state,
                attempts=0,
                created_at=T0 + dt.timedelta(minutes=minutes),
            )

        older, newer = job(art, "queued", 0), job(art, "running", 5)
        finished = job(art, "succeeded", -10)
        single = job(other, "queued", 0)

    command.upgrade(cfg, "a7e3c9d2f480")

    with engine.connect() as conn:
        states: dict[uuid.UUID, str] = {
            r.id: r.state for r in conn.execute(sa.text("SELECT id, state FROM generation_job"))
        }
        detail = conn.execute(
            sa.text("SELECT error_detail FROM generation_job WHERE id = :id"), {"id": older}
        ).scalar()
        indexes = {i["name"] for i in sa.inspect(conn).get_indexes("generation_job")}
    assert states[older] == "cancelled"
    assert "superseded" in (detail or "")
    assert states[newer] == "running"
    assert states[finished] == "succeeded"
    assert states[single] == "queued"
    assert "uq_generation_job_active_artifact" in indexes

    # the index now refuses a second active job for an artifact
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        _insert(
            conn,
            "generation_job",
            artifact_id=art,
            module_id=m,
            kind="generate_artifact",
            state="queued",
            attempts=0,
        )


def test_version_generation_options_backfill_and_downgrade(
    scratch_db: tuple[AlembicConfig, Engine],
) -> None:
    """PR #2 review finding 1: existing versions get their artifact's current options
    (best available); the downgrade drops the column."""
    cfg, engine = scratch_db
    command.upgrade(cfg, "b7d2e4f6a813")
    with engine.begin() as conn:
        module_id = _module(conn, _course(conn, "opts"))
        artifact_id = _artifact(conn, module_id, published=True, kind="quiz")
        conn.execute(
            sa.text("UPDATE artifact SET generation_options = :o WHERE id = :a"),
            {"o": '{"language": "ta", "difficulty": "hard"}', "a": artifact_id},
        )
    command.upgrade(cfg, "a3f9c1d5e7b2")
    with engine.connect() as conn:
        options = conn.scalar(
            sa.text("SELECT generation_options FROM artifact_version WHERE artifact_id = :a"),
            {"a": artifact_id},
        )
    assert options == {"language": "ta", "difficulty": "hard"}
    command.downgrade(cfg, "b7d2e4f6a813")
    with engine.connect() as conn:
        cols = sa.inspect(conn).get_columns("artifact_version")
    assert "generation_options" not in {c["name"] for c in cols}
    command.upgrade(cfg, "head")
