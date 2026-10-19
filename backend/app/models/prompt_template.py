from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.coltypes import artifact_type_enum
from app.models.enums import ArtifactType


class PromptTemplate(Base, TimestampMixin):
    """Admin-editable system prompt for one artifact type, passed to NotebookLM
    as `focus_prompt`. Versioned; exactly one active row per `artifact_type`.
    """

    __tablename__ = "prompt_template"
    __table_args__ = (
        # Partial unique index: at most one is_active=true per type.
        Index(
            "uq_prompt_template_active_per_type",
            "artifact_type",
            unique=True,
            postgresql_where="is_active",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    artifact_type: Mapped[ArtifactType] = mapped_column(
        artifact_type_enum, nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
