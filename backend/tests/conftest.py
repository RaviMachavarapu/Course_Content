"""Shared pytest fixtures.

Tests run against a dedicated database (``<db>_test``, or ``TEST_DATABASE_URL``
if set) that is created on demand and migrated to head once per session. Each
test executes inside an outer transaction that is rolled back on teardown, so
tests are fully isolated and the dev database is never touched.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
import redis
import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

# Tests must never reach live NotebookLM, even when the shell or a local
# docker-compose.override.yml sets CONTENT_PROVIDER=notebooklm — set before any
# app import reads the settings. (A run with the override once created ~100
# test notebooks in the signed-in Google account, 2026-10-22.)
os.environ["CONTENT_PROVIDER"] = "fixture"

from app.api.deps import get_redis as app_get_redis
from app.config import get_settings
from app.db.session import get_db as app_get_db
from app.main import create_app

if TYPE_CHECKING:
    from app.storage.service import Storage

_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _test_database_url() -> str:
    if env := os.environ.get("TEST_DATABASE_URL"):
        return env
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def _ensure_database(url: str) -> None:
    target = make_url(url)
    admin = target.set(database="postgres")
    engine = create_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": target.database},
            ).scalar()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE "{target.database}"'))
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    url = _test_database_url()
    _ensure_database(url)

    cfg = AlembicConfig(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    engine = create_engine(url, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_connection(db_engine: Engine) -> Iterator[Connection]:
    conn = db_engine.connect()
    txn = conn.begin()
    try:
        yield conn
    finally:
        txn.rollback()
        conn.close()


@pytest.fixture
def db_session(db_connection: Connection) -> Iterator[Session]:
    """Commits inside a test become SAVEPOINTs within the outer transaction, so
    everything is undone when `db_connection` rolls back.
    """
    factory = sessionmaker(
        bind=db_connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def media_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Storage:
    """Isolate every test's media writes to a temp dir. Patches `get_storage` in
    each module that imported it by name."""
    from app.storage.service import Storage

    store = Storage(tmp_path / "media", get_settings().public_base_url)
    for module in (
        "app.storage.service",
        "app.pipeline.orchestrator",
        "app.api.media",
        "app.api.admin.artifacts",
        "app.api.admin.jobs",
        "app.api.admin.uploads",
        "app.api.admin.courses",
        "app.pipeline.module_sources",
        "app.render.typeset_docs",
        "app.pipeline.artifact_pdf",
    ):
        monkeypatch.setattr(f"{module}.get_storage", lambda: store, raising=False)
    return store


@pytest.fixture
def source_step_sessions(
    db_connection: Connection,
) -> Callable[[], AbstractContextManager[Session]]:
    """A `session_scope` stand-in for the module source step: each session is
    bound to the test connection, so its commits are SAVEPOINTs inside the
    test's outer transaction (and visible to `db_session`)."""
    factory = sessionmaker(
        bind=db_connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    @contextmanager
    def scope() -> Iterator[Session]:
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return scope


@pytest.fixture(autouse=True)
def _bind_source_step(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The orchestrator's source step opens its own sessions (`session_scope`, the
    app database) and a Redis lock (db 0). In a DB test, bind both to the test
    connection and the test Redis db instead."""
    if "db_session" not in request.fixturenames:
        return
    from app.pipeline import module_sources, orchestrator

    monkeypatch.setattr(
        orchestrator,
        "ensure_module_sources",
        functools.partial(
            module_sources.ensure_module_sources,
            session_factory=request.getfixturevalue("source_step_sessions"),
            redis_client=request.getfixturevalue("redis_client"),
        ),
    )


@pytest.fixture
def redis_client() -> Iterator[redis.Redis[str]]:
    """A flushed, isolated Redis DB (index 15, or TEST_REDIS_DB for a parallel
    run against another test database) for the duration of one test."""
    url = os.environ.get("TEST_REDIS_URL") or get_settings().redis_url
    db = int(os.environ.get("TEST_REDIS_DB", "15"))
    # A db in the URL path (redis://host:6379/0) overrides a `db=` kwarg to
    # from_url, which made this flush the app's real db0 (every session and
    # rate limit) on each run. Take host/auth from the URL, force the test db.
    assert db >= 10, "test Redis DBs are 10-15; 0-2 belong to the running app"
    base = redis.Redis.from_url(url, decode_responses=True)
    client: redis.Redis[str] = redis.Redis(**{**base.connection_pool.connection_kwargs, "db": db})
    base.close()
    assert client.connection_pool.connection_kwargs["db"] == db
    client.flushdb()
    try:
        yield client
    finally:
        client.flushdb()
        client.close()


@pytest.fixture
def client(db_session: Session, redis_client: redis.Redis[str]) -> Iterator[TestClient]:
    app = create_app()

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[app_get_db] = _override_get_db
    app.dependency_overrides[app_get_redis] = lambda: redis_client
    with TestClient(app) as test_client:
        _send_csrf_like_the_spa(test_client)
        yield test_client
    app.dependency_overrides.clear()


def _send_csrf_like_the_spa(test_client: TestClient) -> None:
    """Mirror frontend/src/lib/api.ts: on a non-GET request, copy the `sdp_csrf`
    cookie into `X-CSRF-Token` unless the test set that header itself (an
    explicit empty value is how a test sends "no token")."""

    def add_token(request: httpx.Request) -> None:
        if request.method in {"GET", "HEAD", "OPTIONS"} or "x-csrf-token" in request.headers:
            return
        token = test_client.cookies.get("sdp_csrf")
        if token:
            request.headers["X-CSRF-Token"] = token

    test_client.event_hooks["request"].append(add_token)
