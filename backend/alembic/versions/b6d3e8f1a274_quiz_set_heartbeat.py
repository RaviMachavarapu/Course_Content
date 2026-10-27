"""adaptive quiz: heartbeat on question sets

Revision ID: b6d3e8f1a274
Revises: f4a7c2e9d851
Create Date: 2026-10-27 23:30:00.000000+00:00

Adds `quiz_question_set.heartbeat_at` (timestamptz, nullable): the last sign of
life of the task preparing a chat set, so a crashed preparation is replaced
after minutes rather than hours. NULL = use `created_at` (sets made before).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6d3e8f1a274"
down_revision: str | None = "f4a7c2e9d851"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quiz_question_set",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("quiz_question_set", "heartbeat_at")
