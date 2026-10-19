"""T003 — request-context middleware and CORS."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_request_id_generated_and_returned(client: TestClient) -> None:
    resp = client.get("/api/openapi.json")
    rid = resp.headers.get("X-Request-ID")
    assert rid and len(rid) >= 16


def test_request_id_is_per_request(client: TestClient) -> None:
    a = client.get("/api/openapi.json").headers["X-Request-ID"]
    b = client.get("/api/openapi.json").headers["X-Request-ID"]
    assert a != b


def test_incoming_request_id_is_honoured(client: TestClient) -> None:
    resp = client.get("/api/openapi.json", headers={"X-Request-ID": "caller-supplied-id-123"})
    assert resp.headers["X-Request-ID"] == "caller-supplied-id-123"


def test_cors_allows_spa_origin_only(client: TestClient) -> None:
    allowed = client.get("/api/openapi.json", headers={"Origin": "http://localhost:5173"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    other = client.get("/api/openapi.json", headers={"Origin": "http://evil.example"})
    assert other.headers.get("access-control-allow-origin") != "http://evil.example"
