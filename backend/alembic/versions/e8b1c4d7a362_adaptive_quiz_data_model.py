"""adaptive quiz: question sets, attempt links, retake switch

Revision ID: e8b1c4d7a362
Revises: d7a3e6c2b145
Create Date: 2026-10-27 20:00:00.000000+00:00

Adds `quiz_question_set` (per-student question sets, with a partial unique
index allowing one pending/ready chat set per student+quiz), links attempts to
their set (`quiz_attempt.question_set_id`, `completed_at`), and adds
`module.quiz_fresh_retakes` (default on).

Downgrade is one-way in practice: it drops the question sets but keeps
attempts whose answers use the per-answer shape and whose questions came from
a (chat) set, which pre-adaptive code would grade against the Studio quiz. It
refuses to run while such attempts exist unless `-x allow_data_loss=1` is given.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "e8b1c4d7a362"
down_revision: str | None = "d7a3e6c2b145"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _refuse_data_loss(count_sql: str, what: str) -> None:
    """Downgrade guard (review 2026-10-28): refuse to destroy data silently.
    Override with `alembic -x allow_data_loss=1 downgrade ...`."""
    if context.get_x_argument(as_dictionary=True).get("allow_data_loss") == "1":
        return
    n = op.get_bind().execute(sa.text(count_sql)).scalar() or 0
    if n:
        raise RuntimeError(
            f"refusing to downgrade: {n} {what}. "
            "Re-run with -x allow_data_loss=1 to accept that."
        )


def upgrade() -> None:
    op.create_table(
        "quiz_question_set",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Enum("studio", "chat", name="quiz_set_source"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("preparing", "ready", "used", "failed", name="quiz_set_status"),
            nullable=False,
        ),
        sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("validation_report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifact.id"],
            name=op.f("fk_quiz_question_set_artifact_id_artifact"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name=op.f("fk_quiz_question_set_user_id_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_question_set")),
    )
    op.create_index(
        "ix_quiz_question_set_artifact_user_status",
        "quiz_question_set",
        ["artifact_id", "user_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_quiz_question_set_pending_chat",
        "quiz_question_set",
        ["artifact_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("source = 'chat' AND status IN ('preparing', 'ready')"),
    )
    op.add_column("quiz_attempt", sa.Column("question_set_id", sa.Uuid(), nullable=True))
    op.add_column(
        "quiz_attempt", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        op.f("ix_quiz_attempt_question_set_id"), "quiz_attempt", ["question_set_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_quiz_attempt_question_set_id_quiz_question_set"),
        "quiz_attempt",
        "quiz_question_set",
        ["question_set_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "module",
        sa.Column(
            "quiz_fresh_retakes", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
    )


def downgrade() -> None:
    _refuse_data_loss(
        "SELECT count(*) FROM quiz_attempt WHERE question_set_id IS NOT NULL",
        "quiz attempt(s) were made with question sets the old code can't read",
    )
    op.drop_column("module", "quiz_fresh_retakes")
    op.drop_constraint(
        op.f("fk_quiz_attempt_question_set_id_quiz_question_set"),
        "quiz_attempt",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_quiz_attempt_question_set_id"), table_name="quiz_attempt")
    op.drop_column("quiz_attempt", "completed_at")
    op.drop_column("quiz_attempt", "question_set_id")
    op.drop_index("uq_quiz_question_set_pending_chat", table_name="quiz_question_set")
    op.drop_index("ix_quiz_question_set_artifact_user_status", table_name="quiz_question_set")
    op.drop_table("quiz_question_set")
    sa.Enum(name="quiz_set_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="quiz_set_source").drop(op.get_bind(), checkfirst=True)
