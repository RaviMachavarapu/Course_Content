"""pdf sources: module source files, uploads, source-step columns

Revision ID: b3e8a1d54f27
Revises: 9d4b2f61c7e8
Create Date: 2026-10-26 12:00:00.000000+00:00

Adds the `module_source_file` and `source_upload` tables, the four module
columns that track the once-per-module "add sources to NotebookLM" step, and
makes `module.source_url` nullable (a module may have PDFs and no link).
Modules that already have a notebook were created with their link added, so
their sources count as ready.

Downgrade is one-way in practice: PDF-only modules (no link) can't exist in
the old schema, so they are deleted with their artifacts, attempts and
progress, and their PDFs are left on disk. It refuses to run while such
modules exist unless `-x allow_data_loss=1` is given.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "b3e8a1d54f27"
down_revision: str | None = "9d4b2f61c7e8"
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
        "module_source_file",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column(
            "parts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["module.id"],
            name=op.f("fk_module_source_file_module_id_module"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_module_source_file")),
    )
    op.create_index(
        op.f("ix_module_source_file_module_id"), "module_source_file", ["module_id"], unique=False
    )
    op.create_table(
        "source_upload",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admin_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("received_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "status",
            sa.Enum("receiving", "complete", "claimed", name="source_upload_status"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["user.id"],
            name=op.f("fk_source_upload_admin_id_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_upload")),
    )
    op.create_index(op.f("ix_source_upload_admin_id"), "source_upload", ["admin_id"], unique=False)

    op.add_column("module", sa.Column("notebooklm_link_source_id", sa.String(255), nullable=True))
    op.add_column(
        "module", sa.Column("sources_ready_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("module", sa.Column("sources_error", sa.Text(), nullable=True))
    op.add_column(
        "module", sa.Column("sources_failed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column("module", "source_url", existing_type=sa.String(2048), nullable=True)
    op.execute(
        "UPDATE module SET sources_ready_at = now() WHERE notebooklm_notebook_id IS NOT NULL"
    )


def downgrade() -> None:
    _refuse_data_loss(
        "SELECT count(*) FROM module WHERE source_url IS NULL",
        "PDF-only module(s) would be deleted (artifacts, attempts, progress; "
        "their PDFs stay on disk)",
    )
    # A module with no link has nothing to put in a NOT NULL source_url, so
    # those (PDF-only) modules are deleted first; their artifacts cascade.
    op.execute("DELETE FROM module WHERE source_url IS NULL")
    op.alter_column("module", "source_url", existing_type=sa.String(2048), nullable=False)
    op.drop_column("module", "sources_failed_at")
    op.drop_column("module", "sources_error")
    op.drop_column("module", "sources_ready_at")
    op.drop_column("module", "notebooklm_link_source_id")
    op.drop_index(op.f("ix_source_upload_admin_id"), table_name="source_upload")
    op.drop_table("source_upload")
    op.drop_index(op.f("ix_module_source_file_module_id"), table_name="module_source_file")
    op.drop_table("module_source_file")
    op.execute("DROP TYPE source_upload_status")
