"""quiz questions-only pdf media kind

Revision ID: d7a3e6c2b145
Revises: c5f2a7d913e0
Create Date: 2026-10-27 18:00:00.000000+00:00

Adds `quiz_questions_pdf`: the students' copy of a quiz's typeset PDF
(questions and options, no answer key). `quiz_pdf` stays admin-only.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d7a3e6c2b145"
down_revision: str | None = "c5f2a7d913e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = "quiz_questions_pdf"
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
    "flashcards_pdf",
    "quiz_pdf",
    "infographic_pdf",
    "slides_handout_pdf",
]


def upgrade() -> None:
    # ADD VALUE can't be used inside the transaction that adds it.
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE media_file_kind ADD VALUE IF NOT EXISTS '{_NEW}'")


def downgrade() -> None:
    # Postgres can't drop an enum value: delete its rows and rebuild the type.
    op.execute(f"DELETE FROM media_file WHERE kind::text = '{_NEW}'")
    op.execute("ALTER TYPE media_file_kind RENAME TO media_file_kind_old")
    op.execute(f"CREATE TYPE media_file_kind AS ENUM ({', '.join(repr(v) for v in _OLD)})")
    op.execute(
        "ALTER TABLE media_file ALTER COLUMN kind TYPE media_file_kind "
        "USING kind::text::media_file_kind"
    )
    op.execute("DROP TYPE media_file_kind_old")
