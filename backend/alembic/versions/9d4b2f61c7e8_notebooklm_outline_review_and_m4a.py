"""notebooklm outline review and m4a audio

Revision ID: 9d4b2f61c7e8
Revises: 7c1e5d2a9b40
Create Date: 2026-10-22 22:00:00.000000+00:00

Adds the `outline_review` artifact status, the `audio_m4a` media kind
(NotebookLM's Audio Overview is audio/mp4), and the two artifact columns the
slide-outline review uses.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9d4b2f61c7e8"
down_revision: str | None = "7c1e5d2a9b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD VALUE can't be used inside the transaction that adds it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE artifact_status ADD VALUE IF NOT EXISTS 'outline_review'")
        op.execute("ALTER TYPE media_file_kind ADD VALUE IF NOT EXISTS 'audio_m4a'")
    op.add_column(
        "artifact",
        sa.Column("outline_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("artifact", sa.Column("notebooklm_studio_id", sa.Text(), nullable=True))


def _drop_enum_value(type_name: str, table: str, column: str, values: list[str]) -> None:
    """Rebuild `type_name` with only `values` (Postgres can't drop a value)."""
    op.execute(f"ALTER TYPE {type_name} RENAME TO {type_name}_old")
    op.execute(f"CREATE TYPE {type_name} AS ENUM ({', '.join(repr(v) for v in values)})")
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {type_name} "
        f"USING {column}::text::{type_name}"
    )
    op.execute(f"DROP TYPE {type_name}_old")


def downgrade() -> None:
    op.drop_column("artifact", "notebooklm_studio_id")
    op.drop_column("artifact", "outline_json")
    # Rows using the new values can't be represented afterwards.
    op.execute("UPDATE artifact SET status = 'error' WHERE status = 'outline_review'")
    op.execute("DELETE FROM media_file WHERE kind = 'audio_m4a'")
    _drop_enum_value(
        "artifact_status",
        "artifact",
        "status",
        ["pending", "processing", "ready", "error", "published"],
    )
    _drop_enum_value(
        "media_file_kind",
        "media_file",
        "kind",
        [
            "pptx",
            "slide_png",
            "deck_pdf",
            "report_pdf",
            "infographic_png",
            "infographic_svg",
            "audio_mp3",
            "cover",
            "hero",
        ],
    )
