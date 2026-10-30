from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.artifact import Artifact
    from app.models.media_file import MediaFile


class ArtifactVersion(Base):
    """An immutable snapshot from one generation or redo run (D7)."""

    __tablename__ = "artifact_version"
    __table_args__ = (
        UniqueConstraint("artifact_id", "revision", name="uq_artifact_version_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifact.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generation_job.id", ondelete="SET NULL"), nullable=True
    )
    prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_template.id", ondelete="SET NULL"), nullable=True
    )
    prompt_template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    focus_prompt_used: Mapped[str] = mapped_column(Text, nullable=False, default="")
    redo_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    notebooklm_artifact_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: The generation options this run actually used (language, difficulty, ...; the
    #: artifact's `generation_options` as sent with the NotebookLM request). The
    #: artifact's own options may change later (a Redo with new options), so a published
    #: version keeps what it was made with. None for versions stored before 2026-10-30
    #: that the backfill could not fill.
    generation_options: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    artifact: Mapped[Artifact] = relationship(back_populates="versions", foreign_keys=[artifact_id])
    media_files: Mapped[list[MediaFile]] = relationship(
        back_populates="artifact_version",
        cascade="all, delete-orphan",
    )
