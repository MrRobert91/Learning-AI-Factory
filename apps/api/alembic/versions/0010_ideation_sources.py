"""Persist ideation sources and research policy.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ideation_sessions",
        sa.Column("research_mode", sa.String(length=30), nullable=False, server_default="web_only"),
    )
    op.add_column(
        "projects",
        sa.Column("research_mode", sa.String(length=30), nullable=False, server_default="web_only"),
    )
    op.create_table(
        "ideation_sources",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=True),
        sa.Column("project_id", sa.String(length=32), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["ideation_sessions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ideation_sources_session_id", "ideation_sources", ["session_id"], unique=False
    )
    op.create_index(
        "ix_ideation_sources_project_id", "ideation_sources", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_ideation_sources_project_id", table_name="ideation_sources")
    op.drop_index("ix_ideation_sources_session_id", table_name="ideation_sources")
    op.drop_table("ideation_sources")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("research_mode")
    with op.batch_alter_table("ideation_sessions") as batch:
        batch.drop_column("research_mode")
