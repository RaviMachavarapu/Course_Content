"""Every state-changing student route requires the CSRF token (review 2026-10-28;
docs/PROJECT_FRAME.md: "same-site cookies + a CSRF token on state-changing
requests"). The SPA already sends X-CSRF-Token on every non-GET request."""

from __future__ import annotations

import uuid

import pytest
from fastapi import status
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import create_app

_SAFE = {"GET", "HEAD", "OPTIONS"}
# reachable before a session exists (login/register) or deliberately public
_PRE_AUTH_PREFIX = "/api/student/auth/"


def _student_mutations() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for route in create_app().routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/student/"):
            continue
        if route.path.startswith(_PRE_AUTH_PREFIX):
            continue
        out.extend((route.path, m) for m in sorted(route.methods - _SAFE))
    return out


MUTATIONS = _student_mutations()


def test_the_known_mutations_are_covered() -> None:
    paths = {p for p, _ in MUTATIONS}
    assert "/api/student/artifacts/{artifact_id}/progress" in paths
    assert "/api/student/quiz-attempts/{attempt_id}/answers" in paths
    assert "/api/student/quiz-attempts/{attempt_id}/complete" in paths
    assert any("flashcard-ratings" in p for p in paths)


@pytest.mark.parametrize(("path", "method"), MUTATIONS)
def test_student_mutation_without_csrf_is_403(client: TestClient, path: str, method: str) -> None:
    r = client.post(
        "/api/student/auth/register",
        json={"email": "s@example.com", "password": "strong-pass-123", "display_name": "S"},
    )
    assert r.status_code == status.HTTP_201_CREATED
    url = path
    for name in ("artifact_id", "attempt_id", "card_index", "index"):
        url = url.replace("{" + name + "}", str(uuid.uuid4()) if "id" in name else "0")
    # an explicit empty header opts out of the test client's SPA behaviour
    resp = client.request(method, url, json={}, headers={"X-CSRF-Token": ""})
    assert resp.status_code == status.HTTP_403_FORBIDDEN, (path, resp.text)
    assert resp.json()["error"]["code"] == "csrf_failed"
