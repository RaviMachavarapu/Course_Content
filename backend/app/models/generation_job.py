from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.coltypes import generation_job_kind_enum, generation_job_state_enum
from app.models.enums import GenerationJobKind, GenerationJobState


class GenerationJob(Base):
    __tablename__ = "generation_job"
    __table_args__ = (
        # One artifact is never generated twice at once: at most one active job each.
        Index(
            "uq_generation_job_active_artifact",
            "artifact_id",
            unique=True,
            postgresql_where=text("state IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[GenerationJobKind] = mapped_column(generation_job_kind_enum, nullable=False)
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("module.id", ondelete="CASCADE"), nullable=True, index=True
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artifact.id", ondelete="CASCADE"), nullable=True, index=True
    )
    state: Mapped[GenerationJobState] = mapped_column(
        generation_job_state_enum, nullable=False, default=GenerationJobState.queued
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Last sign of life: set when claimed/requeued and touched every minute by the
    #: worker running it; the reaper fails jobs whose heartbeat stopped.
    heartbeat_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
