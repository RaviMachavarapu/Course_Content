"""course_progress.completed_at: the Course Complete badge stays once earned

Revision ID: e5c1a9d7b3f2
Revises: a7e3c9d2f480
Create Date: 2026-10-29 12:00:00.000000+00:00

Owner decision 2026-10-29: the badge is never revoked when a module is
published later (or a deck republished). The progress write that completes a
course stamps `completed_at`; it is never cleared.

Upgrade backfills courses complete right now with their latest completion
(the date the badge already showed). Downgrade drops the column.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5c1a9d7b3f2"
down_revision: str | None = "a7e3c9d2f480"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "course_progress",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE course_progress AS cp
        SET completed_at = done.at
        FROM (
            SELECT p.id, max(ap.completed_at) AS at
            FROM course_progress AS p
            JOIN module AS m ON m.course_id = p.course_id
            JOIN artifact AS a ON a.module_id = m.id AND a.published_version_id IS NOT NULL
            LEFT JOIN artifact_progress AS ap
              ON ap.artifact_id = a.id
             AND ap.user_id = p.user_id
             AND ap.completed_at IS NOT NULL
            GROUP BY p.id
            HAVING count(*) = count(ap.completed_at)
        ) AS done
        WHERE cp.id = done.id
        """
    )


def downgrade() -> None:
    op.drop_column("course_progress", "completed_at")
