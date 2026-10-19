"""T004 — session dependency, migrations, and per-test isolation."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

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
