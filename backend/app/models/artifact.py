from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.coltypes import artifact_status_enum, artifact_type_enum
from app.models.enums import ArtifactStatus, ArtifactType

if TYPE_CHECKING:
    from app.models.artifact_version import ArtifactVersion
    from app.models.module import Module


class Artifact(Base, TimestampMixin):
    __tablename__ = "artifact"
    __table_args__ = (UniqueConstraint("module_id", "type", name="uq_artifact_module_type"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("module.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[ArtifactType] = mapped_column(artifact_type_enum, nullable=False)
    status: Mapped[ArtifactStatus] = mapped_column(
        artifact_status_enum, nullable=False, default=ArtifactStatus.pending
    )
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artifact_version.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artifact_version.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Per-type generation knobs (language, quantity/difficulty, audio
    #: format/length, infographic orientation — app/schemas/content_options.py).
    #: Forwarded verbatim to `ContentProvider.generate`'s `options` dict.
    generation_options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    #: Admin-written focus text for this artifact. When set, it is sent to
    #: NotebookLM *instead of* the type's Settings prompt template (owner
    #: decision 2026-10-20); `None` means "use the template".
    custom_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: While `status` is `outline_review`: NotebookLM's draft slide outline
    #: ({"style": str, "slides": [str]}) and the NotebookLM artifact it belongs to.
    outline_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    notebooklm_studio_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What was sent for `notebooklm_studio_id` ({focus_prompt, redo_note,
    #: template_id, template_version}). Kept after a timeout or a failure once
    #: NotebookLM had the artifact, so Retry resumes it instead of regenerating.
    studio_request: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    module: Mapped[Module] = relationship(back_populates="artifacts")
    versions: Mapped[list[ArtifactVersion]] = relationship(
        back_populates="artifact",
        cascade="all, delete-orphan",
        order_by="ArtifactVersion.revision",
        foreign_keys="ArtifactVersion.artifact_id",
    )
