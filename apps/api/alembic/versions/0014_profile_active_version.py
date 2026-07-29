"""Track the active version of each agent profile.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_profiles") as batch:
        batch.add_column(
            sa.Column(
                "active_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )

    op.execute(
        sa.text(
            "UPDATE agent_profiles "
            "SET active_version = version "
            "WHERE active_version != version"
        )
    )

    with op.batch_alter_table("agent_profiles") as batch:
        batch.alter_column("active_version", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("agent_profiles") as batch:
        batch.drop_column("active_version")
