"""Prompt-template service.

Seed bodies live in ``app/prompts/<type>.md`` (owner-editable placeholders).
On first run they populate one active `prompt_template` per artifact type.
Admins edit them via the Settings API; each edit creates a **new active version**
and deactivates the previous one (spec.md §5.4, BR6).
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ARTIFACT_TYPES, ArtifactType
from app.models.prompt_template import PromptTemplate

_SEED_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=len(ARTIFACT_TYPES))
def seed_body(artifact_type: ArtifactType) -> str:
    return (_SEED_DIR / f"{artifact_type.value}.md").read_text(encoding="utf-8").strip()


def get_active_template(session: Session, artifact_type: ArtifactType) -> PromptTemplate | None:
    return session.scalar(
        select(PromptTemplate).where(
            PromptTemplate.artifact_type == artifact_type,
            PromptTemplate.is_active.is_(True),
        )
    )


def get_active_body(session: Session, artifact_type: ArtifactType) -> str:
    """The body the orchestrator feeds to NotebookLM as `focus_prompt` (BR6).

    Self-heals: if no active row exists yet, seed it now.
    """
    template = get_active_template(session, artifact_type)
    if template is None:
        template = _insert(session, artifact_type, seed_body(artifact_type), version=1)
    return template.body


def _insert(
    session: Session,
    artifact_type: ArtifactType,
    body: str,
    *,
    version: int,
    updated_by: uuid.UUID | None = None,
) -> PromptTemplate:
    row = PromptTemplate(
        artifact_type=artifact_type,
        version=version,
        body=body,
        is_active=True,
        updated_by=updated_by,
    )
    session.add(row)
    session.flush()
    return row


def seed_prompt_templates(session: Session) -> int:
    """Insert a v1 active template for any type that has none. Idempotent;
    returns the number of rows inserted."""
    inserted = 0
    for artifact_type in ARTIFACT_TYPES:
        if get_active_template(session, artifact_type) is None:
            _insert(session, artifact_type, seed_body(artifact_type), version=1)
            inserted += 1
    return inserted


def update_prompt(
    session: Session,
    artifact_type: ArtifactType,
    body: str,
    *,
    updated_by: uuid.UUID | None = None,
) -> PromptTemplate:
    """Deactivate the current active template and insert a new active version.

    If nothing has been seeded yet, the seed body is inserted as v1 first so it
    is preserved in the version history.
    """
    current = get_active_template(session, artifact_type)
    if current is None:
        current = _insert(session, artifact_type, seed_body(artifact_type), version=1)

    current.is_active = False
    next_version = current.version + 1
    session.flush()  # release the partial-unique-index slot before re-insert
    return _insert(
        session, artifact_type, body.strip(), version=next_version, updated_by=updated_by
    )


def restore_default(
    session: Session,
    artifact_type: ArtifactType,
    *,
    updated_by: uuid.UUID | None = None,
) -> PromptTemplate:
    return update_prompt(session, artifact_type, seed_body(artifact_type), updated_by=updated_by)


def version_history(session: Session, artifact_type: ArtifactType) -> list[PromptTemplate]:
    return list(
        session.scalars(
            select(PromptTemplate)
            .where(PromptTemplate.artifact_type == artifact_type)
            .order_by(PromptTemplate.version.desc())
        )
    )
