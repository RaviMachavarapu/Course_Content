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
    ModuleSourceType,
    PromptTemplate,
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
