from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.coltypes import module_source_type_enum, module_status_enum
from app.models.enums import ModuleSourceType, ModuleStatus

if TYPE_CHECKING:
    from app.models.artifact import Artifact
    from app.models.course import Course
    from app.models.module_source_file import ModuleSourceFile


class Module(Base, TimestampMixin):
    __tablename__ = "module"
    __table_args__ = (UniqueConstraint("course_id", "order_index", name="uq_module_course_order"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("course.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_type: Mapped[ModuleSourceType] = mapped_column(module_source_type_enum, nullable=False)
    source_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notebooklm_notebook_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Once-per-module "add sources to NotebookLM" step (link + PDFs).
    notebooklm_link_source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sources_ready_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sources_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources_failed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[ModuleStatus] = mapped_column(
        module_status_enum, nullable=False, default=ModuleStatus.processing
    )

    course: Mapped[Course] = relationship(back_populates="modules")
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
    )
    source_files: Mapped[list[ModuleSourceFile]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        order_by="ModuleSourceFile.order_index",
    )
