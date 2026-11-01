"""typeset pdf media kinds

Revision ID: c5f2a7d913e0
Revises: b3e8a1d54f27
Create Date: 2026-10-27 12:00:00.000000+00:00

Adds the media kinds for the Quarto-typeset PDFs of flashcards, quizzes,
infographics and slide-deck handouts (reports reuse `report_pdf`).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c5f2a7d913e0"
down_revision: str | None = "b3e8a1d54f27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = ["flashcards_pdf", "quiz_pdf", "infographic_pdf", "slides_handout_pdf"]
_OLD = [
    "pptx",
    "slide_png",
    "deck_pdf",
    "report_pdf",
    "infographic_png",
    "infographic_svg",
    "audio_mp3",
    "audio_m4a",
    "cover",
    "hero",
]


def upgrade() -> None:
    # ADD VALUE can't be used inside the transaction that adds it.
    with op.get_context().autocommit_block():
        for value in _NEW:
            op.execute(f"ALTER TYPE media_file_kind ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Rows using the new values can't be represented afterwards (Postgres can't
    # drop an enum value, so the type is rebuilt without them).
    op.execute(
        "DELETE FROM media_file WHERE kind::text IN (" + ", ".join(repr(v) for v in _NEW) + ")"
    )
    op.execute("ALTER TYPE media_file_kind RENAME TO media_file_kind_old")
    op.execute(f"CREATE TYPE media_file_kind AS ENUM ({', '.join(repr(v) for v in _OLD)})")
    op.execute(
        "ALTER TABLE media_file ALTER COLUMN kind TYPE media_file_kind "
        "USING kind::text::media_file_kind"
    )
    op.execute("DROP TYPE media_file_kind_old")
