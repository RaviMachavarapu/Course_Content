"""add artifact custom_prompt

Revision ID: 7c1e5d2a9b40
Revises: 4ef3a950b2b0
Create Date: 2026-10-20 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c1e5d2a9b40"
down_revision: str | None = "4ef3a950b2b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("artifact", sa.Column("custom_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("artifact", "custom_prompt")
