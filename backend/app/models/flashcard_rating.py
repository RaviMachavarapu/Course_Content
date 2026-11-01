from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.coltypes import flashcard_rating_enum
from app.models.enums import FlashcardRatingValue


class FlashcardRating(Base):
    """A student's Hard/Good/Easy on one card of one *published version* of a
    deck: a newly published deck starts unrated (owner decision 2026-10-28)."""

    __tablename__ = "flashcard_rating"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "artifact_version_id",
            "card_index",
            name="uq_flashcard_rating_user_version_card",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifact.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifact_version.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_index: Mapped[int] = mapped_column(Integer, nullable=False)
    rating: Mapped[FlashcardRatingValue] = mapped_column(flashcard_rating_enum, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
