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
    __tablename__ = "flashcard_rating"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "artifact_id", "card_index", name="uq_flashcard_rating_user_artifact_card"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artifact.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_index: Mapped[int] = mapped_column(Integer, nullable=False)
    rating: Mapped[FlashcardRatingValue] = mapped_column(flashcard_rating_enum, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
