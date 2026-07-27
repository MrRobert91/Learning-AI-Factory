"""Persist immutable provider usage and attributable costs.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=True),
        sa.Column("job_id", sa.String(length=32), nullable=True),
        sa.Column("workflow_step", sa.Integer(), nullable=True),
        sa.Column("agent", sa.String(length=50), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("input_characters", sa.Integer(), nullable=False),
        sa.Column("output_units", sa.Integer(), nullable=False),
        sa.Column("image_count", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("cost_source", sa.String(length=30), nullable=False),
        sa.Column("pricing_snapshot_json", sa.Text(), nullable=False),
        sa.Column("artifact_id", sa.String(length=32), nullable=True),
        sa.Column("work_unit_key", sa.String(length=320), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_usage_records_idempotency_key"
        ),
    )
    for column in (
        "project_id",
        "job_id",
        "agent",
        "operation",
        "model",
        "cost_source",
        "artifact_id",
        "created_at",
    ):
        op.create_index(
            f"ix_usage_records_{column}", "usage_records", [column], unique=False
        )


def downgrade() -> None:
    for column in (
        "created_at",
        "artifact_id",
        "cost_source",
        "model",
        "operation",
        "agent",
        "job_id",
        "project_id",
    ):
        op.drop_index(f"ix_usage_records_{column}", table_name="usage_records")
    op.drop_table("usage_records")
