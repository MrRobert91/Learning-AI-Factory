"""Artifact generation metadata.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "artifacts",
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
    )
    connection = op.get_bind()
    for artifact_type in ("slide_deck", "video"):
        connection.execute(
            sa.text(
                "UPDATE artifacts SET metadata_json = :metadata "
                "WHERE type = :artifact_type"
            ),
            {
                "artifact_type": artifact_type,
                "metadata": '{"orientation":"horizontal","width":1920,"height":1080}',
            },
        )


def downgrade() -> None:
    with op.batch_alter_table("artifacts") as batch:
        batch.drop_column("metadata_json")
