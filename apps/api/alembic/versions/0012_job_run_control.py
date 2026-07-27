"""Persist cooperative job run control.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("control_json", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("control_json")
