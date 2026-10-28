"""Student flashcard ratings (spec.md §3.11) — Hard / Good / Easy per card."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import CurrentStudent, DbDep
from app.api.student.artifacts import _visible_artifact
from app.errors import APIError
from app.models.enums import ArtifactType, FlashcardRatingValue
from app.models.flashcard_rating import FlashcardRating
from app.schemas.student import FlashcardRatingRequest, FlashcardRatingsResponse
from app.services.progress import published_ratings

router = APIRouter(prefix="/api/student", tags=["student-flashcards"])


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

    assert version is not None  # cards came from it
    rating = FlashcardRatingValue(body.value)
    # one statement, so two first ratings of a card can't race into a 500
    db.execute(
        insert(FlashcardRating)
        .values(
            id=uuid.uuid4(),
            user_id=student.id,
            artifact_id=artifact.id,
            artifact_version_id=version.id,
            card_index=card_index,
            rating=rating,
        )
        .on_conflict_do_update(
            constraint="uq_flashcard_rating_user_version_card",
            set_={"rating": rating, "updated_at": func.now()},
        )
    )
    return FlashcardRatingsResponse(
        ratings=published_ratings(db, student.id, version.id, len(cards))
    )
