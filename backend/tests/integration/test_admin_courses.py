"""T025 — admin courses & module ingestion API."""

from __future__ import annotations

import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.cli import seed_admin

ALL_TYPES = ["slide_deck", "flashcards", "quiz", "report", "infographic", "audio_overview"]


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.admin.courses._dispatch_all", lambda *a, **k: None)


def _admin(client: TestClient, db: Session) -> dict[str, str]:
    seed_admin(db, email="c@example.com", display_name="C", password="courses-admin-pw-1")
    db.flush()
    client.post(
        "/api/admin/auth/login", json={"email": "c@example.com", "password": "courses-admin-pw-1"}
    )
    return {"X-CSRF-Token": client.cookies["sdp_csrf"]}


def test_requires_admin(client: TestClient) -> None:
    assert client.get("/api/admin/courses").status_code == status.HTTP_401_UNAUTHORIZED


def test_create_course_and_list(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    r = client.post(
        "/api/admin/courses",
        json={"title": "Intro to ML", "description": "d", "category": "AI"},
        headers=h,
    )
    assert r.status_code == status.HTTP_201_CREATED
    course = r.json()["course"]
    assert course["slug"] == "intro-to-ml"
    assert course["modules"] == []

    listing = client.get("/api/admin/courses").json()["courses"]
    assert any(c["id"] == course["id"] and c["module_count"] == 0 for c in listing)


def test_slug_is_uniquified(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    a = client.post("/api/admin/courses", json={"title": "Dup"}, headers=h).json()["course"]
    b = client.post("/api/admin/courses", json={"title": "Dup"}, headers=h).json()["course"]
    assert {a["slug"], b["slug"]} == {"dup", "dup-2"}


def test_create_module_starts_generation(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "C1"}, headers=h).json()["course"]["id"]

    r = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://www.youtube.com/watch?v=abc",
            "title": "Module 1",
            "types": ["report", "quiz"],
        },
        headers=h,
    )
    assert r.status_code == status.HTTP_201_CREATED
    body = r.json()
    mod = body["module"]
    assert mod["source_type"] == "youtube"
    assert mod["order_index"] == 0
    assert len(mod["artifacts"]) == 6  # BR1 — all six rows exist
    assert len(body["job_ids"]) == 2

    detail = client.get(f"/api/admin/courses/{cid}").json()["course"]
    assert len(detail["modules"]) == 1
    assert detail["modules"][0]["status"] in ("processing", "pending_review")


def test_create_module_stores_per_type_generation_options(
    client: TestClient, db_session: Session
) -> None:
    from sqlalchemy import select

    from app.models.artifact import Artifact
    from app.models.module import Module

    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "C2"}, headers=h).json()["course"]["id"]

    r = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://www.youtube.com/watch?v=opts",
            "title": "Module 1",
            # "report" is requested but given no options entry, to prove it
            # still gets that type's defaults, not an empty dict.
            "types": ["quiz", "audio_overview", "infographic", "report"],
            "options": {
                "quiz": {"quantity": "more", "difficulty": "hard"},
                "audio_overview": {"format": "debate", "length": "short", "language": "hi"},
                "infographic": {"orientation": "portrait"},
            },
        },
        headers=h,
    )
    assert r.status_code == status.HTTP_201_CREATED
    module_id = r.json()["module"]["id"]

    module = db_session.get(Module, module_id)
    assert module is not None
    by_type = {a.type.value: a for a in module.artifacts}
    assert by_type["quiz"].generation_options == {
        "quantity": "more",
        "difficulty": "hard",
        "language": "en",
    }
    assert by_type["audio_overview"].generation_options == {
        "format": "debate",
        "length": "short",
        "language": "hi",
    }
    # orientation given, the rest defaulted
    assert by_type["infographic"].generation_options == {
        "orientation": "portrait",
        "language": "en",
        "detail": "standard",
        "style": "auto",
    }
    # requested but no options entry -> that type's defaults, not empty
    assert by_type["report"].generation_options == {
        "format": "interactive",
        "template": None,
        "language": "en",
    }
    # BR1's other rows exist but weren't requested for this ingest — left
    # untouched (empty) until they're actually generated
    slide_deck = db_session.scalar(
        select(Artifact).where(Artifact.module_id == module_id, Artifact.type == "slide_deck")
    )
    assert slide_deck is not None
    assert slide_deck.generation_options == {}


def test_create_module_stores_custom_prompts(client: TestClient, db_session: Session) -> None:
    from app.models.module import Module

    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "CP"}, headers=h).json()["course"]["id"]
    r = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://www.youtube.com/watch?v=prompts",
            "title": "Module 1",
            "types": ["quiz", "flashcards", "report"],
            "prompts": {"quiz": " Three questions on chapter 1 ", "flashcards": "   "},
        },
        headers=h,
    )
    assert r.status_code == status.HTTP_201_CREATED
    module = db_session.get(Module, r.json()["module"]["id"])
    assert module is not None
    by_type = {a.type.value: a for a in module.artifacts}
    assert by_type["quiz"].custom_prompt == "Three questions on chapter 1"
    assert by_type["flashcards"].custom_prompt is None  # blank -> template
    assert by_type["report"].custom_prompt is None  # omitted -> template


def test_create_module_rejects_bad_option_value(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "C3"}, headers=h).json()["course"]["id"]

    r = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={
            "source_url": "https://www.youtube.com/watch?v=bad",
            "title": "Module 1",
            "types": ["quiz"],
            "options": {"quiz": {"difficulty": "extreme"}},  # not a real choice
        },
        headers=h,
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert r.json()["error"]["code"] == "validation_error"


def test_module_rejects_unsupported_source(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "C2"}, headers=h).json()["course"]["id"]
    r = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={"source_url": "ftp://nope", "title": "m", "types": ["report"]},
        headers=h,
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert r.json()["error"]["code"] == "unsupported_source"


def test_module_requires_at_least_one_type(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "C3"}, headers=h).json()["course"]["id"]
    r = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={"source_url": "https://example.com/a", "title": "m", "types": []},
        headers=h,
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_patch_and_delete_module_cascades(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = client.post("/api/admin/courses", json={"title": "C4"}, headers=h).json()["course"]["id"]
    client.patch(f"/api/admin/courses/{cid}", json={"category": "Data"}, headers=h)
    assert client.get(f"/api/admin/courses/{cid}").json()["course"]["category"] == "Data"

    mid = client.post(
        f"/api/admin/courses/{cid}/modules",
        json={"source_url": "https://example.com/x", "title": "m", "types": ["report"]},
        headers=h,
    ).json()["module"]["id"]
    assert (
        client.request("DELETE", f"/api/admin/courses/modules/{mid}", headers=h).status_code
        == status.HTTP_204_NO_CONTENT
    )
    assert client.get(f"/api/admin/courses/{cid}").json()["course"]["modules"] == []


# -- PDF sources (Task 5) ----------------------------------------------------
def _pdf_bytes(pages: int = 1) -> bytes:
    import io

    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _upload(client: TestClient, h: dict[str, str], name: str, data: bytes) -> str:
    r = client.post(
        "/api/admin/uploads", json={"file_name": name, "size_bytes": len(data)}, headers=h
    )
    uid = r.json()["upload_id"]
    r = client.put(
        f"/api/admin/uploads/{uid}?offset=0",
        content=data,
        headers={**h, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code == 200
    return uid


def _course(client: TestClient, h: dict[str, str]) -> str:
    return client.post("/api/admin/courses", json={"title": "PDF C"}, headers=h).json()["course"][
        "id"
    ]


def _post_module(client: TestClient, h: dict[str, str], cid: str, **extra: object):  # type: ignore[no-untyped-def]
    body = {"title": "m", "types": ["report"], **extra}
    return client.post(f"/api/admin/courses/{cid}/modules", json=body, headers=h)


def test_create_module_link_only(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = _course(client, h)
    r = _post_module(client, h, cid, source_url="https://www.youtube.com/watch?v=abc")
    assert r.status_code == 201
    mod = r.json()["module"]
    assert mod["source_type"] == "youtube"
    assert mod["source_url"] == "https://www.youtube.com/watch?v=abc"
    assert mod["source_files"] == []


def test_create_module_pdfs_only(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = _course(client, h)
    u1 = _upload(client, h, "one.pdf", _pdf_bytes(2))
    u2 = _upload(client, h, "two.pdf", _pdf_bytes(3))
    r = _post_module(client, h, cid, upload_ids=[u1, u2])
    assert r.status_code == 201, r.text
    mod = r.json()["module"]
    assert mod["source_type"] == "pdf"
    assert mod["source_url"] is None
    assert [f["file_name"] for f in mod["source_files"]] == ["one.pdf", "two.pdf"]
    assert all(f["part_count"] == 1 for f in mod["source_files"])

    from app.models.module import Module

    m = db_session.get(Module, uuid.UUID(mod["id"]))
    assert m is not None
    rows = m.source_files
    assert [r_.page_count for r_ in rows] == [2, 3]
    assert [r_.order_index for r_ in rows] == [0, 1]
    assert all(len(r_.checksum_sha256) == 64 and r_.parts == [] for r_ in rows)
    from app.storage.service import get_storage

    assert all(get_storage().exists(r_.storage_key) for r_ in rows)
    assert not get_storage().exists(f"uploads/{u1}.pdf")


def test_create_module_link_and_pdfs(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = _course(client, h)
    u1 = _upload(client, h, "one.pdf", _pdf_bytes())
    r = _post_module(client, h, cid, source_url="https://example.com/article", upload_ids=[u1])
    assert r.status_code == 201, r.text
    mod = r.json()["module"]
    assert mod["source_type"] == "web"
    assert mod["source_url"] == "https://example.com/article"
    assert len(mod["source_files"]) == 1


def test_create_module_needs_a_source(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = _course(client, h)
    r = _post_module(client, h, cid)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "no_source"
    assert r.json()["error"]["message"] == "Add a link or at least one PDF"
    r = _post_module(client, h, cid, source_url="  ", upload_ids=[])
    assert r.json()["error"]["code"] == "no_source"


def test_cannot_claim_incomplete_or_foreign_upload(client: TestClient, db_session: Session) -> None:
    h = _admin(client, db_session)
    cid = _course(client, h)
    data = _pdf_bytes()
    # incomplete
    r = client.post(
        "/api/admin/uploads", json={"file_name": "x.pdf", "size_bytes": len(data)}, headers=h
    )
    partial = r.json()["upload_id"]
    assert (
        _post_module(client, h, cid, upload_ids=[partial]).json()["error"]["code"] == "bad_upload"
    )
    # unknown
    unknown = str(uuid.uuid4())
    assert (
        _post_module(client, h, cid, upload_ids=[unknown]).json()["error"]["code"] == "bad_upload"
    )
    # already claimed
    done = _upload(client, h, "y.pdf", data)
    assert _post_module(client, h, cid, upload_ids=[done]).status_code == 201
    assert _post_module(client, h, cid, upload_ids=[done]).json()["error"]["code"] == "bad_upload"
    # foreign
    from app.models.source_upload import SourceUpload

    other = _upload(client, h, "z.pdf", data)
    row = db_session.get(SourceUpload, uuid.UUID(other))
    assert row is not None
    from app.models.user import User

    foreign = db_session.scalar(
        __import__("sqlalchemy").select(User).where(User.id != row.admin_id)
    )
    if foreign is None:
        seed_admin(db_session, email="o@example.com", display_name="O", password="other-admin-pw-1")
        db_session.flush()
        foreign = db_session.scalar(
            __import__("sqlalchemy").select(User).where(User.email == "o@example.com")
        )
    assert foreign is not None
    row.admin_id = foreign.id
    db_session.flush()
    assert _post_module(client, h, cid, upload_ids=[other]).json()["error"]["code"] == "bad_upload"


def test_unsafe_filename_gets_safe_key(client: TestClient, db_session: Session) -> None:
    import re

    h = _admin(client, db_session)
    cid = _course(client, h)
    uid = _upload(client, h, "../Ünï cödé notes.pdf", _pdf_bytes())
    r = _post_module(client, h, cid, upload_ids=[uid])
    assert r.status_code == 201, r.text
    from app.models.module import Module

    m = db_session.get(Module, uuid.UUID(r.json()["module"]["id"]))
    assert m is not None
    row = m.source_files[0]
    assert row.file_name == "../Ünï cödé notes.pdf"
    assert re.search(r"sources/00-[A-Za-z0-9._-]+\.pdf$", row.storage_key)


def test_create_module_makes_no_provider_calls(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.pipeline.fixture import FixtureProvider

    calls: list[str] = []
    for name in ("create_notebook", "add_source", "add_pdf_source"):
        if hasattr(FixtureProvider, name):
            monkeypatch.setattr(
                FixtureProvider, name, lambda *a, _n=name, **k: calls.append(_n) or None
            )
    h = _admin(client, db_session)
    cid = _course(client, h)
    uid = _upload(client, h, "a.pdf", _pdf_bytes())
    r = _post_module(client, h, cid, source_url="https://example.com/a", upload_ids=[uid])
    assert r.status_code == 201, r.text
    assert calls == []
