"""Agent profiles (versioned), jobs with events, artifacts.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_profiles",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("agent_type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("soul_md", sa.Text(), nullable=False),
        sa.Column("agents_md", sa.Text(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_profiles_agent_type", "agent_profiles", ["agent_type"])
    op.create_table(
        "agent_profile_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "profile_id",
            sa.String(32),
            sa.ForeignKey("agent_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("soul_md", sa.Text(), nullable=False),
        sa.Column("agents_md", sa.Text(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("note", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_profile_versions_profile_id", "agent_profile_versions", ["profile_id"]
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_table(
        "job_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "job_id", sa.String(32), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column(
            "created_by_job_id",
            sa.String(32),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])


def downgrade() -> None:
    for index, table in [
        ("ix_artifacts_project_id", "artifacts"),
        ("ix_job_events_job_id", "job_events"),
        ("ix_jobs_status", "jobs"),
        ("ix_jobs_project_id", "jobs"),
        ("ix_agent_profile_versions_profile_id", "agent_profile_versions"),
        ("ix_agent_profiles_agent_type", "agent_profiles"),
    ]:
        op.drop_index(index, table_name=table)
    for table in ["artifacts", "job_events", "jobs", "agent_profile_versions", "agent_profiles"]:
        op.drop_table(table)
