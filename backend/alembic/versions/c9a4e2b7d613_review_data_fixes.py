"""review fixes: flashcard ratings per published version; unique media keys

Revision ID: c9a4e2b7d613
Revises: b6d3e8f1a274
Create Date: 2026-10-28 12:00:00.000000+00:00

- `flashcard_rating.artifact_version_id` (NOT NULL, FK → artifact_version,
  cascade): ratings belong to one published version of a deck, so a newly
  published deck starts unrated (owner decision 2026-10-28). Existing ratings
  attach to their artifact's current published version; ratings of a deck
  with no published version (none can be made through the API) are deleted.
  The unique key becomes (user_id, artifact_version_id, card_index).
- `media_file.storage_key` gets a unique constraint (and so an index): every
  media request looks a file up by key. Upgrade refuses to run if duplicate
  keys exist (resolve them by hand; keys carry the revision, so none should).

Downgrade: ratings of older versions of a deck collapse to the newest rating
per (user, deck, card) — the older ones are deleted.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9a4e2b7d613"
down_revision: str | None = "b6d3e8f1a274"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # -- flashcard ratings scoped to the published version --------------------
    op.add_column(
        "flashcard_rating",
        sa.Column("artifact_version_id", sa.Uuid(), nullable=True),
    )
    op.execute(
        """
        UPDATE flashcard_rating AS fr
        SET artifact_version_id = a.published_version_id
        FROM artifact AS a
        WHERE a.id = fr.artifact_id
        """
    )
    op.execute("DELETE FROM flashcard_rating WHERE artifact_version_id IS NULL")
    op.alter_column("flashcard_rating", "artifact_version_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_flashcard_rating_artifact_version_id_artifact_version"),
        "flashcard_rating",
        "artifact_version",
        ["artifact_version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_flashcard_rating_artifact_version_id"),
        "flashcard_rating",
        ["artifact_version_id"],
    )
    op.drop_constraint("uq_flashcard_rating_user_artifact_card", "flashcard_rating", type_="unique")
    op.create_unique_constraint(
        "uq_flashcard_rating_user_version_card",
        "flashcard_rating",
        ["user_id", "artifact_version_id", "card_index"],
    )

    # -- unique media keys -----------------------------------------------------
    dupes = bind.execute(
        sa.text(
            "SELECT count(*) FROM (SELECT storage_key FROM media_file "
            "GROUP BY storage_key HAVING count(*) > 1) AS d"
        )
    ).scalar()
    if dupes:
        raise RuntimeError(
            f"media_file has {dupes} duplicated storage_key value(s); "
            "remove the duplicate rows before upgrading"
        )
    op.create_unique_constraint(op.f("uq_media_file_storage_key"), "media_file", ["storage_key"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_media_file_storage_key"), "media_file", type_="unique")

    # keep only the newest rating per (user, deck, card) for the old unique key
    op.execute(
        """
        DELETE FROM flashcard_rating AS fr
        USING flashcard_rating AS newer
        WHERE newer.user_id = fr.user_id
          AND newer.artifact_id = fr.artifact_id
          AND newer.card_index = fr.card_index
          AND (newer.updated_at, newer.id) > (fr.updated_at, fr.id)
        """
    )
    op.drop_constraint("uq_flashcard_rating_user_version_card", "flashcard_rating", type_="unique")
    op.create_unique_constraint(
        "uq_flashcard_rating_user_artifact_card",
        "flashcard_rating",
        ["user_id", "artifact_id", "card_index"],
    )
    op.drop_index(op.f("ix_flashcard_rating_artifact_version_id"), table_name="flashcard_rating")
    op.drop_constraint(
        op.f("fk_flashcard_rating_artifact_version_id_artifact_version"),
        "flashcard_rating",
        type_="foreignkey",
    )
    op.drop_column("flashcard_rating", "artifact_version_id")
