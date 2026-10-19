"""T003 — health endpoint and OpenAPI schema."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_shape(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert set(body) == {"status", "db", "redis"}
    assert body["status"] in ("ok", "degraded")
    # 200 iff both dependencies report ok
    healthy = body["db"] == "ok" and body["redis"] == "ok"
    assert (resp.status_code == 200) is healthy


def test_openapi_served(client: TestClient) -> None:
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"].startswith("Shikshak Dp")


def test_docs_served(client: TestClient) -> None:
    assert client.get("/api/docs").status_code == 200
