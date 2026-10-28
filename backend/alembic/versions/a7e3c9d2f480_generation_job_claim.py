"""generation jobs: one active job per artifact, heartbeat; persisted Studio request

Revision ID: a7e3c9d2f480
Revises: c9a4e2b7d613
Create Date: 2026-10-28 18:00:00.000000+00:00

- `generation_job.heartbeat_at`: the worker running a job touches it every
  minute; the reaper (beat) fails a `running` job whose heartbeat stopped
  (worker killed mid-generation) and a `queued` job nobody picked up.
- `uq_generation_job_active_artifact`: at most one queued/running job per
  artifact, so one artifact can never be generated twice at once. Upgrade
  first cancels every active job of an artifact except its newest (they could
  only exist through the duplicate-run bug this closes).
- `artifact.studio_request`: what was sent to NotebookLM for the artifact
  `notebooklm_studio_id` names (focus prompt, redo note, template id/version),
  kept after a timeout or a post-creation failure so Retry resumes that
  NotebookLM artifact instead of generating (and paying for) a new one.

Downgrade drops the three; cancelled jobs stay cancelled.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7e3c9d2f480"
down_revision: str | None = "c9a4e2b7d613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_job",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "artifact",
        sa.Column("studio_request", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        """
        UPDATE generation_job AS j
        SET state = 'cancelled',
            finished_at = now(),
            error_detail = coalesce(j.error_detail, 'superseded by a newer job for this artifact')
        WHERE j.state IN ('queued', 'running')
          AND j.artifact_id IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM generation_job AS newer
            WHERE newer.artifact_id = j.artifact_id
              AND newer.state IN ('queued', 'running')
              AND (newer.created_at, newer.id) > (j.created_at, j.id)
          )
        """
    )
    op.create_index(
        "uq_generation_job_active_artifact",
        "generation_job",
        ["artifact_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_generation_job_active_artifact", table_name="generation_job")
    op.drop_column("artifact", "studio_request")
    op.drop_column("generation_job", "heartbeat_at")
