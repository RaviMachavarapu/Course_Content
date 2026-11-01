from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CourseProgress(Base):
    __tablename__ = "course_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_course_progress_user_course"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("course.id", ondelete="CASCADE"), nullable=False, index=True
    )
    percent_complete: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    last_module_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("module.id", ondelete="SET NULL"), nullable=True
    )
    # "Course Complete" badge: stamped the first time every published artifact
    # of the course was complete, never cleared (a module published later, or a
    # deck republished, doesn't take the badge back or move its date).
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ArtifactProgress(Base):
    __tablename__ = "artifact_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "artifact_id", name="uq_artifact_progress_user_artifact"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifact.id", ondelete="CASCADE"), nullable=False, index=True
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("module.id", ondelete="CASCADE"), nullable=False, index=True
    )
    viewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audio_position_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slide_last_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
