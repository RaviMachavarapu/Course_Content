"""T014 — prompt-template service."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.enums import ARTIFACT_TYPES, ArtifactType
from app.models.prompt_template import PromptTemplate
from app.services import prompts as svc


def _count(db: Session, artifact_type: ArtifactType) -> int:
    return (
        db.scalar(
            sa.select(sa.func.count())
            .select_from(PromptTemplate)
            .where(PromptTemplate.artifact_type == artifact_type)
        )
        or 0
    )


def test_seed_is_idempotent(db_session: Session) -> None:
    assert svc.seed_prompt_templates(db_session) == len(ARTIFACT_TYPES)
    assert svc.seed_prompt_templates(db_session) == 0
    for t in ARTIFACT_TYPES:
        active = svc.get_active_template(db_session, t)
        assert active is not None and active.version == 1


def test_get_active_body_self_heals(db_session: Session) -> None:
    body = svc.get_active_body(db_session, ArtifactType.quiz)
    assert "TODO(owner)" in body
    assert svc.get_active_template(db_session, ArtifactType.quiz) is not None


def test_update_creates_new_active_version_and_deactivates_prior(db_session: Session) -> None:
    svc.get_active_body(db_session, ArtifactType.report)  # v1
    v2 = svc.update_prompt(db_session, ArtifactType.report, "  my new body  ")
    assert v2.version == 2
    assert v2.is_active is True
    assert v2.body == "my new body"  # trimmed
    assert _count(db_session, ArtifactType.report) == 2
    actives = db_session.scalars(
        sa.select(PromptTemplate).where(
            PromptTemplate.artifact_type == ArtifactType.report,
            PromptTemplate.is_active.is_(True),
        )
    ).all()
    assert len(actives) == 1 and actives[0].version == 2


def test_restore_default_resets_body_as_a_new_version(db_session: Session) -> None:
    svc.update_prompt(db_session, ArtifactType.flashcards, "custom")  # v2
    restored = svc.restore_default(db_session, ArtifactType.flashcards)  # v3
    assert restored.version == 3
    assert restored.body == svc.seed_body(ArtifactType.flashcards)
