"""Persist the selected workflow per project.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column("selected_workflow_id", sa.String(length=32), nullable=True)
        )
        batch.create_foreign_key(
            "fk_projects_selected_workflow_id_workflows",
            "workflows",
            ["selected_workflow_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint(
            "fk_projects_selected_workflow_id_workflows",
            type_="foreignkey",
        )
        batch.drop_column("selected_workflow_id")
