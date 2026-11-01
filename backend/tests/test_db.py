"""T004 — session dependency, migrations, and per-test isolation."""

from __future__ import annotations

import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppMeta

_SENTINEL_KEY = "isolation-probe"


def test_can_write_and_read_within_a_test(db_session: Session) -> None:
    db_session.add(AppMeta(key=_SENTINEL_KEY, value="hello"))
    db_session.commit()
    row = db_session.get(AppMeta, _SENTINEL_KEY)
    assert row is not None and row.value == "hello"
    assert row.created_at is not None and row.updated_at is not None


def test_previous_test_did_not_leak(db_session: Session) -> None:
    # If rollback isolation works, the row from the test above is gone.
    assert db_session.get(AppMeta, _SENTINEL_KEY) is None


def test_schema_is_at_head(db_session: Session) -> None:
    tables = set(sa.inspect(db_session.get_bind()).get_table_names())
    assert {"app_meta", "alembic_version"} <= tables
    version = db_session.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    assert version and len(version) == 12


def _backfill_db_url() -> tuple[str, str]:
    base = make_url(get_settings().database_url)
    name = f"shikshak_test_mig_{uuid.uuid4().hex[:8]}"
    return base.set(database="postgres").render_as_string(hide_password=False), name


def test_migration_backfills_sources_ready_for_existing_notebooks() -> None:
    """Runs on a throwaway database so the shared test DB stays at head and the
    dev DB is never touched."""
    admin_url, name = _backfill_db_url()
    url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    try:
        backend = Path(__file__).resolve().parent.parent
        cfg = AlembicConfig(str(backend / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend / "alembic"))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "9d4b2f61c7e8")

        engine = create_engine(url)
        course_id, with_nb, without_nb = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO course (id, title, slug, description, category, status) "
                    "VALUES (:id, 'c', :slug, 'd', 'cat', 'draft')"
                ),
                {"id": course_id, "slug": f"c-{course_id}"},
            )
            for i, (mid, nb) in enumerate([(with_nb, "nb-1"), (without_nb, None)]):
                conn.execute(
                    sa.text(
                        "INSERT INTO module (id, course_id, order_index, title, source_url, "
                        "source_type, notebooklm_notebook_id, status) "
                        "VALUES (:id, :cid, :i, 't', 'https://example.com', 'web', :nb, "
                        "'processing')"
                    ),
                    {"id": mid, "cid": course_id, "i": i, "nb": nb},
                )

        command.upgrade(cfg, "head")

        with engine.connect() as conn:
            rows = dict(
                conn.execute(sa.text("SELECT id, sources_ready_at IS NOT NULL FROM module")).all()
            )
        engine.dispose()
        assert rows[with_nb] is True
        assert rows[without_nb] is False
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
