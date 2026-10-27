from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.coltypes import quiz_set_source_enum, quiz_set_status_enum
from app.models.enums import QuizSetSource, QuizSetStatus


class QuizQuestionSet(Base):
    """One set of quiz questions served to one student.

    `questions` holds the full questions including answers: server-only, never
    sent to students before they check an answer.
    """

    __tablename__ = "quiz_question_set"
    __table_args__ = (
        Index("ix_quiz_question_set_artifact_user_status", "artifact_id", "user_id", "status"),
        # Idempotent preparation: at most one pending/ready chat set per student+quiz.
        Index(
            "uq_quiz_question_set_pending_chat",
            "artifact_id",
            "user_id",
            unique=True,
            postgresql_where=text("source = 'chat' AND status IN ('preparing', 'ready')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifact.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[QuizSetSource] = mapped_column(quiz_set_source_enum, nullable=False)
    status: Mapped[QuizSetStatus] = mapped_column(
        quiz_set_status_enum, nullable=False, default=QuizSetStatus.preparing
    )
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    #: last sign of life of the task preparing this set (bumped when it claims the set,
    #: before each chat round and before each retry); NULL = use `created_at`
    heartbeat_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def alive_at(self) -> dt.datetime:
        """When the preparing task last showed it was alive (heartbeat, else creation)."""
        return self.heartbeat_at or self.created_at
