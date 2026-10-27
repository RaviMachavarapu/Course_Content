"""adaptive quiz: per-attempt MCQ option order

Revision ID: f4a7c2e9d851
Revises: e8b1c4d7a362
Create Date: 2026-10-27 23:00:00.000000+00:00

Adds `quiz_attempt.option_orders` (JSONB, nullable): the shuffled display order
of each MCQ's options, drawn once per attempt. NULL = stored order (attempts
opened before shuffling).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f4a7c2e9d851"
down_revision: str | None = "e8b1c4d7a362"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quiz_attempt",
        sa.Column("option_orders", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("quiz_attempt", "option_orders")
