"""T017 — storage keys, filesystem service, and superseded-media GC."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.course import Course
from app.models.enums import ArtifactType, MediaFileKind, ModuleSourceType
from app.models.module import Module
from app.storage.keys import InvalidKeyError, media_key, validate_key
from app.storage.service import Storage

IDS = {k: uuid.uuid4() for k in ("course", "module", "artifact")}


def test_media_key_scheme() -> None:
    key = media_key(
        course_id=IDS["course"],
        module_id=IDS["module"],
        artifact_id=IDS["artifact"],
        revision=3,
        kind=MediaFileKind.slide_png,
        ext="png",
        page_index=2,
    )
    assert key == (
        f"courses/{IDS['course']}/modules/{IDS['module']}"
        f"/artifacts/{IDS['artifact']}/v3/slide_png.0002.png"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "../secret",
        "/etc/passwd",
        "a//b",
        "a/../b",
        "a/./b",
        "a\\b",
        "trailing/",
        "  spaced/key",
        "a/b\x00c",
    ],
)
def test_validate_key_rejects_dangerous_keys(bad: str) -> None:
    with pytest.raises(InvalidKeyError):
        validate_key(bad)


def test_put_open_delete_roundtrip(tmp_path: Path) -> None:
    storage = Storage(tmp_path, "http://localhost:5173")
    stored = storage.put("courses/x/f.txt", b"hello world", "text/plain")
    assert stored.size_bytes == 11
    assert stored.checksum_sha256 == (
        "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    )
    assert storage.open("courses/x/f.txt") == b"hello world"
    assert storage.exists("courses/x/f.txt") is True
    assert storage.delete("courses/x/f.txt") is True
    assert storage.exists("courses/x/f.txt") is False
    assert storage.delete("courses/x/f.txt") is False


def test_put_rejects_traversal(tmp_path: Path) -> None:
    storage = Storage(tmp_path, "http://x")
    with pytest.raises(InvalidKeyError):
        storage.put("../escape.txt", b"x", "text/plain")


def test_url_for(tmp_path: Path) -> None:
    storage = Storage(tmp_path, "http://localhost:5173/")
    assert storage.url_for("courses/x/a.pdf") == "http://localhost:5173/api/media/courses/x/a.pdf"


def _artifact_with_versions(db: Session, storage: Storage, n_versions: int) -> Artifact:
    course = Course(title="C", slug=f"c-{uuid.uuid4()}")
    module = Module(
        course=course,
        order_index=0,
        title="M",
        source_url="https://y/x",
        source_type=ModuleSourceType.youtube,
    )
    artifact = Artifact(module=module, type=ArtifactType.report)
    db.add(artifact)
    db.flush()

    for rev in range(1, n_versions + 1):
        version = ArtifactVersion(artifact_id=artifact.id, revision=rev, focus_prompt_used="p")
        db.add(version)
        db.flush()
        key = media_key(
            course_id=course.id,
            module_id=module.id,
            artifact_id=artifact.id,
            revision=rev,
            kind=MediaFileKind.report_pdf,
            ext="pdf",
        )
        stored = storage.put(key, f"pdf-{rev}".encode(), "application/pdf")
        db.add(
            storage.build_media_file(
                stored, artifact_version_id=str(version.id), kind=MediaFileKind.report_pdf
            )
        )
    db.flush()
    return artifact


def test_gc_keeps_current_published_and_newest_n(tmp_path: Path, db_session: Session) -> None:
    storage = Storage(tmp_path, "http://x")
    artifact = _artifact_with_versions(db_session, storage, n_versions=6)
    versions = sorted(artifact.versions, key=lambda v: v.revision)  # rev 1..6

    artifact.published_version_id = versions[0].id  # rev 1 (protected)
    artifact.current_version_id = versions[5].id  # rev 6 (protected)
    db_session.flush()

    removed = storage.gc_superseded_media(db_session, keep_last_n=2)
    db_session.expire_all()

    # superseded = rev 2,3,4,5 (newest-first: 5,4,3,2); keep 2 -> delete rev 3 and 2
    assert removed == 2
    assert len(list(tmp_path.rglob("*.pdf"))) == 4  # rev 1,4,5,6 survive on disk

    remaining_revs = set(
        db_session.scalars(
            sa.select(ArtifactVersion.revision)
            .join(ArtifactVersion.media_files)
            .where(ArtifactVersion.artifact_id == artifact.id)
        )
    )
    assert remaining_revs == {1, 4, 5, 6}
    # protected versions (rev 1 published, rev 6 current) still have their file
    for rev in (1, 6):
        key = media_key(
            course_id=artifact.module.course_id,
            module_id=artifact.module_id,
            artifact_id=artifact.id,
            revision=rev,
            kind=MediaFileKind.report_pdf,
            ext="pdf",
        )
        assert storage.exists(key)


def test_append_and_move(tmp_path: Path) -> None:
    import hashlib

    store = Storage(tmp_path / "m", "http://x")
    assert store.append("uploads/a.pdf", 0, b"hello ") == 6
    assert store.append("uploads/a.pdf", 6, b"world") == 11
    assert store.sha256("uploads/a.pdf") == hashlib.sha256(b"hello world").hexdigest()
    store.move("uploads/a.pdf", "courses/c/sources/01-a.pdf")
    assert not store.exists("uploads/a.pdf")
    assert store.open("courses/c/sources/01-a.pdf") == b"hello world"


def test_append_wrong_offset_raises(tmp_path: Path) -> None:
    store = Storage(tmp_path / "m", "http://x")
    store.append("uploads/a.pdf", 0, b"abc")
    with pytest.raises(ValueError):
        store.append("uploads/a.pdf", 5, b"zzz")  # beyond the end
    with pytest.raises(ValueError):
        store.append("uploads/new.pdf", 5, b"zzz")
    assert store.open("uploads/a.pdf") == b"abc"


def test_append_truncates_unrecorded_tail(tmp_path: Path) -> None:
    store = Storage(tmp_path / "m", "http://x")
    store.append("uploads/a.pdf", 0, b"abc")
    assert store.append("uploads/a.pdf", 2, b"XY") == 4
    assert store.open("uploads/a.pdf") == b"abXY"


def test_upload_and_source_keys() -> None:
    from app.storage.keys import source_key, upload_key

    u = uuid.uuid4()
    assert upload_key(u) == f"uploads/{u}.pdf"
    assert source_key(IDS["course"], IDS["module"], 3, "paper") == (
        f"courses/{IDS['course']}/modules/{IDS['module']}/sources/03-paper.pdf"
    )
    assert source_key(IDS["course"], IDS["module"], 3, "paper", part=2).endswith(
        "/sources/03-paper.part2.pdf"
    )
