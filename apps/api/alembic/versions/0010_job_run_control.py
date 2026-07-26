"""Persist cooperative job run control.

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
        "jobs",
        sa.Column("control_json", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("control_json")
