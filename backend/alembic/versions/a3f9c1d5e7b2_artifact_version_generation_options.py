"""artifact_version.generation_options: the options each version was made with

Revision ID: a3f9c1d5e7b2
Revises: b7d2e4f6a813
Create Date: 2026-10-30 10:00:00.000000+00:00

PR #2 review finding 1 (owner decision 2026-10-30): quiz retakes follow the
language/difficulty of the PUBLISHED quiz version, so each version records the
options it was generated with. Existing versions get their artifact's current
options — the best available record of what they were made with.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f9c1d5e7b2"
down_revision: str | None = "b7d2e4f6a813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "artifact_version",
        sa.Column("generation_options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        """
        UPDATE artifact_version AS v
        SET generation_options = a.generation_options
        FROM artifact AS a
        WHERE v.artifact_id = a.id AND v.generation_options IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("artifact_version", "generation_options")
