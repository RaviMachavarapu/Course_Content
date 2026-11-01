"""generation_job.dispatch: the job's Celery message, kept as an outbox

Revision ID: b7d2e4f6a813
Revises: e5c1a9d7b3f2
Create Date: 2026-10-29 17:00:00.000000+00:00

Review 2026-10-29: a dispatch message lost on the way (broker down at enqueue,
an api restart, a Redis restart) left the job `queued` for 6 h. The message's
queue, kwargs and time limits are stored with the job, so the reaper can send
it again when the broker no longer holds it. Nullable: older rows have none.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d2e4f6a813"
down_revision: str | None = "e5c1a9d7b3f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_job",
        sa.Column("dispatch", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generation_job", "dispatch")
