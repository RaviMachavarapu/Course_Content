"""Student flashcard ratings (spec.md §3.11) — Hard / Good / Easy per card."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import CurrentStudent, DbDep
from app.api.student.artifacts import _visible_artifact
from app.errors import APIError
from app.models.enums import ArtifactType, FlashcardRatingValue
from app.models.flashcard_rating import FlashcardRating
from app.schemas.student import FlashcardRatingRequest, FlashcardRatingsResponse

router = APIRouter(prefix="/api/student", tags=["student-flashcards"])


def _ratings_map(db: DbDep, user_id: uuid.UUID, artifact_id: uuid.UUID) -> dict[int, str]:
    rows = db.scalars(
        select(FlashcardRating).where(
            FlashcardRating.user_id == user_id,
            FlashcardRating.artifact_id == artifact_id,
        )
    )
    return {r.card_index: r.rating.value for r in rows}


@router.put(
    "/artifacts/{artifact_id}/flashcard-ratings/{card_index}",
    response_model=FlashcardRatingsResponse,
)
def rate_card(
    artifact_id: uuid.UUID,
    card_index: int,
    body: FlashcardRatingRequest,
    db: DbDep,
    student: CurrentStudent,
) -> FlashcardRatingsResponse:
    artifact = _visible_artifact(db, artifact_id)
    if artifact.type is not ArtifactType.flashcards:
        raise APIError(status.HTTP_404_NOT_FOUND, "not_found", "Not available")

    version = next((v for v in artifact.versions if v.id == artifact.published_version_id), None)
    cards = (version.content_json or {}).get("cards", []) if version else []
    if not (0 <= card_index < len(cards)):
        raise APIError(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_card_index", "Card index out of range"
        )

    row = db.scalar(
        select(FlashcardRating).where(
            FlashcardRating.user_id == student.id,
            FlashcardRating.artifact_id == artifact.id,
            FlashcardRating.card_index == card_index,
        )
    )
    if row is None:
        row = FlashcardRating(user_id=student.id, artifact_id=artifact.id, card_index=card_index)
        db.add(row)
    row.rating = FlashcardRatingValue(body.value)
    db.flush()

    return FlashcardRatingsResponse(ratings=_ratings_map(db, student.id, artifact.id))
