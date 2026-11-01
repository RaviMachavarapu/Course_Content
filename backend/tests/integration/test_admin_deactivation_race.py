"""Review 2026-10-29 (scenario 14): two admins deactivating each other at the
same moment must leave one active admin (only the CLI could recover from
none). Real connections with committed rows, cleaned up afterwards."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.admin.settings import set_admin_active
from app.errors import APIError
from app.models.user import User, UserRole
from app.schemas.settings import AdminUserPatchRequest


class _NoSessions:
    def revoke_user(self, user_id: str) -> None:
        pass


NO_SESSIONS: Any = _NoSessions()


@pytest.fixture
def two_admins(db_engine: Engine) -> Iterator[tuple[sessionmaker[Session], uuid.UUID, uuid.UUID]]:
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as s:
        others = s.scalar(
            select(func.count()).where(User.role == UserRole.admin, User.is_active.is_(True))
        )
        assert others == 0, "the test database holds committed admins"
        tag = uuid.uuid4().hex[:8]
        a, b = (
            User(
                email=f"{n}-{tag}@example.com",
                role=UserRole.admin,
                display_name=n,
                password_hash="x",
            )
            for n in ("a", "b")
        )
        s.add_all([a, b])
        s.commit()
        ids = (a.id, b.id)
    try:
        yield factory, *ids
    finally:
        with factory() as s:
            s.execute(text('DELETE FROM "user" WHERE id = ANY(:ids)'), {"ids": list(ids)})
            s.commit()


def test_mutual_deactivation_leaves_one_active_admin(
    two_admins: tuple[sessionmaker[Session], uuid.UUID, uuid.UUID],
) -> None:
    factory, a_id, b_id = two_admins
    off = AdminUserPatchRequest(is_active=False)
    outcome: dict[str, Any] = {}

    t1 = factory()
    a = t1.get(User, a_id)
    assert a is not None
    set_admin_active(b_id, off, t1, a, NO_SESSIONS)  # holds the admin row locks

    def b_deactivates_a() -> None:
        with factory() as t2:
            t2.execute(text("SET LOCAL lock_timeout = '10s'"))
            b = t2.get(User, b_id)
            assert b is not None
            try:
                set_admin_active(a_id, off, t2, b, NO_SESSIONS)
                t2.commit()
                outcome["b"] = "ok"
            except APIError as exc:
                t2.rollback()
                outcome["b"] = exc.code

    thread = threading.Thread(target=b_deactivates_a)
    thread.start()
    thread.join(0.5)  # blocked on A's locks
    t1.commit()
    t1.close()
    thread.join(15)

    assert outcome["b"] == "last_active_admin"
    with factory() as s:
        active = s.scalars(
            select(User.id).where(User.id.in_([a_id, b_id]), User.is_active.is_(True))
        ).all()
    assert active == [a_id]
