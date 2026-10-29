"""T013 — core domain models persist and enforce their key constraints."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    Course,
    Module,
    ModuleSourceFile,
    ModuleSourceType,
    PromptTemplate,
    QuizAttempt,
    QuizQuestionSet,
    QuizSetSource,
    QuizSetStatus,
    SourceUpload,
    SourceUploadStatus,
    User,
    UserRole,
)


def _course_with_module(db: Session) -> Module:
    course = Course(title="ML 101", slug=f"ml-101-{id(db)}", description="d")
    module = Module(
        course=course,
        order_index=0,
        title="Intro",
        source_url="https://youtu.be/x",
        source_type=ModuleSourceType.youtube,
    )
    db.add(course)
    db.flush()
    return module


def test_artifact_unique_per_module_and_type(db_session: Session) -> None:
    module = _course_with_module(db_session)
    db_session.add(Artifact(module=module, type=ArtifactType.quiz, status=ArtifactStatus.pending))
    db_session.flush()
    db_session.add(Artifact(module=module, type=ArtifactType.quiz))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_deleting_a_module_cascades_to_artifacts(db_session: Session) -> None:
    module = _course_with_module(db_session)
    db_session.add(Artifact(module=module, type=ArtifactType.report))
    db_session.flush()
    mid = module.id
    db_session.delete(module)
    db_session.flush()
    remaining = db_session.scalar(
        sa.select(sa.func.count()).select_from(Artifact).where(Artifact.module_id == mid)
    )
    assert remaining == 0


def test_one_active_prompt_template_per_type(db_session: Session) -> None:
    db_session.add(
        PromptTemplate(artifact_type=ArtifactType.quiz, version=1, body="a", is_active=True)
    )
    db_session.flush()
    db_session.add(
        PromptTemplate(artifact_type=ArtifactType.quiz, version=2, body="b", is_active=True)
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_inactive_prompt_templates_do_not_conflict(db_session: Session) -> None:
    db_session.add_all(
        [
            PromptTemplate(artifact_type=ArtifactType.quiz, version=1, body="a", is_active=False),
            PromptTemplate(artifact_type=ArtifactType.quiz, version=2, body="b", is_active=False),
            PromptTemplate(artifact_type=ArtifactType.quiz, version=3, body="c", is_active=True),
        ]
    )
    db_session.flush()  # no error


def test_module_without_link_with_source_files(db_session: Session) -> None:
    course = Course(title="PDFs", slug=f"pdfs-{id(db_session)}", description="d")
    module = Module(
        course=course,
        order_index=0,
        title="From files",
        source_url=None,
        source_type=ModuleSourceType.pdf,
    )
    module.source_files.append(
        ModuleSourceFile(
            order_index=1,
            file_name="b.pdf",
            size_bytes=5_000_000_000,
            checksum_sha256="b" * 64,
            storage_key="module-sources/b.pdf",
            page_count=3,
        )
    )
    module.source_files.append(
        ModuleSourceFile(
            order_index=0,
            file_name="a.pdf",
            size_bytes=10,
            checksum_sha256="a" * 64,
            storage_key="module-sources/a.pdf",
            page_count=1,
            parts=[
                {
                    "first_page": 1,
                    "last_page": 1,
                    "storage_key": "module-sources/a.part1.pdf",
                    "notebooklm_source_id": None,
                }
            ],
        )
    )
    db_session.add(course)
    db_session.flush()
    db_session.expire_all()

    reloaded = db_session.get(Module, module.id)
    assert reloaded is not None
    assert reloaded.source_url is None
    assert reloaded.notebooklm_link_source_id is None
    assert reloaded.sources_ready_at is None
    assert reloaded.sources_error is None
    assert reloaded.sources_failed_at is None
    assert [f.file_name for f in reloaded.source_files] == ["a.pdf", "b.pdf"]
    assert reloaded.source_files[0].parts[0]["last_page"] == 1
    assert reloaded.source_files[1].parts == []
    assert reloaded.source_files[1].size_bytes == 5_000_000_000
    assert reloaded.source_files[1].created_at is not None

    db_session.delete(reloaded)
    db_session.flush()
    assert db_session.scalar(sa.select(sa.func.count()).select_from(ModuleSourceFile)) == 0


def test_source_upload_defaults(db_session: Session) -> None:
    admin = User(
        email=f"up-{id(db_session)}@example.com",
        password_hash="x",
        role=UserRole.admin,
        display_name="Admin",
    )
    db_session.add(admin)
    db_session.flush()
    upload = SourceUpload(
        admin_id=admin.id, file_name="big.pdf", size_bytes=123, storage_key="tmp/uploads/x"
    )
    db_session.add(upload)
    db_session.flush()
    db_session.refresh(upload)
    assert upload.received_bytes == 0
    assert upload.status is SourceUploadStatus.receiving
    assert upload.created_at is not None


def _quiz_setup(db: Session) -> tuple[Artifact, User]:
    module = _course_with_module(db)
    artifact = Artifact(module=module, type=ArtifactType.quiz)
    user = User(
        email=f"s{id(db)}@x.org", role=UserRole.student, password_hash="x", display_name="S"
    )
    db.add_all([artifact, user])
    db.flush()
    return artifact, user


def test_module_quiz_fresh_retakes_defaults_true(db_session: Session) -> None:
    module = _course_with_module(db_session)
    db_session.flush()
    assert module.quiz_fresh_retakes is True


def test_quiz_question_set_defaults(db_session: Session) -> None:
    artifact, user = _quiz_setup(db_session)
    qs = QuizQuestionSet(
        artifact_id=artifact.id, user_id=user.id, source=QuizSetSource.studio, questions=[]
    )
    db_session.add(qs)
    db_session.flush()
    assert qs.status == QuizSetStatus.preparing
    assert qs.validation_report == {}
    assert qs.created_at is not None


def test_one_pending_or_ready_chat_set_per_student_and_quiz(db_session: Session) -> None:
    artifact, user = _quiz_setup(db_session)

    def chat(status: QuizSetStatus) -> QuizQuestionSet:
        return QuizQuestionSet(
            artifact_id=artifact.id,
            user_id=user.id,
            source=QuizSetSource.chat,
            status=status,
            questions=[],
        )

    # used / failed chat sets and studio sets never conflict
    db_session.add_all(
        [chat(QuizSetStatus.used), chat(QuizSetStatus.used), chat(QuizSetStatus.failed)]
    )
    db_session.add_all(
        [
            QuizQuestionSet(
                artifact_id=artifact.id,
                user_id=user.id,
                source=QuizSetSource.studio,
                status=QuizSetStatus.ready,
                questions=[],
            )
            for _ in range(2)
        ]
    )
    db_session.add(chat(QuizSetStatus.preparing))
    db_session.flush()
    db_session.add(chat(QuizSetStatus.ready))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_quiz_attempt_links_set_and_set_null_on_delete(db_session: Session) -> None:
    artifact, user = _quiz_setup(db_session)
    qs = QuizQuestionSet(
        artifact_id=artifact.id, user_id=user.id, source=QuizSetSource.studio, questions=[]
    )
    db_session.add(qs)
    db_session.flush()
    attempt = QuizAttempt(user_id=user.id, artifact_id=artifact.id, question_set_id=qs.id)
    db_session.add(attempt)
    db_session.flush()
    assert attempt.completed_at is None
    db_session.delete(qs)
    db_session.flush()
    db_session.refresh(attempt)
    assert attempt.question_set_id is None


def test_deleting_an_artifact_cascades_to_question_sets(db_session: Session) -> None:
    artifact, user = _quiz_setup(db_session)
    db_session.add(
        QuizQuestionSet(
            artifact_id=artifact.id, user_id=user.id, source=QuizSetSource.studio, questions=[]
        )
    )
    db_session.flush()
    aid = artifact.id
    db_session.delete(artifact)
    db_session.flush()
    assert (
        db_session.scalar(
            sa.select(sa.func.count())
            .select_from(QuizQuestionSet)
            .where(QuizQuestionSet.artifact_id == aid)
        )
        == 0
    )
