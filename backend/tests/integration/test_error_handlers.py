"""Only request input is a 422; a pydantic ValidationError raised while building
a response from stored data is a server bug → 500 (review 2026-10-28)."""

from __future__ import annotations

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.artifact import Artifact
from app.models.enums import ArtifactType
from tests.integration.test_redo import _admin_headers, _module_with_generated


class _Stored(BaseModel):
    count: int


def test_internal_validation_error_is_a_logged_500() -> None:
    app = create_app()

    @app.get("/api/_test/bad-stored-data")
    def bad() -> dict[str, int]:
        return {"count": _Stored.model_validate({"count": "not-a-number"}).count}

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/_test/bad-stored-data")
    assert r.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert r.json()["error"]["code"] == "internal_error"
    assert "count" not in r.text  # no internals leaked


def test_bad_request_body_is_still_422(client: TestClient) -> None:
    r = client.post("/api/student/auth/login", json={"email": "not-an-email"})
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert r.json()["error"]["code"] == "validation_error"


def test_bad_redo_option_is_422_with_fields(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.admin.staging._dispatch", lambda *a, **k: None)
    module = _module_with_generated(db_session, [ArtifactType.quiz])
    quiz = next(a for a in module.artifacts if a.type is ArtifactType.quiz)
    r = client.post(
        f"/api/admin/artifacts/{quiz.id}/redo",
        json={"options": {"difficulty": "extreme"}},
        headers=_admin_headers(client, db_session),
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    body = r.json()["error"]
    assert body["code"] == "validation_error"
    assert body["fields"][0]["loc"] == ["difficulty"]
    db_session.expire_all()
    assert db_session.get(Artifact, quiz.id).generation_options != {"difficulty": "extreme"}
