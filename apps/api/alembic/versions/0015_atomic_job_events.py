"""Make job event sequencing atomic and indexed.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-03
"""

import logging

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "next_event_seq",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    duplicate_jobs = int(
        op.get_bind().execute(
            sa.text(
                """
                SELECT COUNT(*) FROM (
                    SELECT job_id
                    FROM job_events
                    GROUP BY job_id, seq
                    HAVING COUNT(*) > 1
                )
                """
            )
        ).scalar_one()
    )
    logger.info("Atomic event migration found %s duplicate job/seq groups", duplicate_jobs)

    # Only jobs with duplicate sequence numbers are renumbered. Their observable
    # order is repaired deterministically by timestamp and immutable row id.
    op.execute(
        sa.text(
            """
            WITH duplicate_jobs AS (
                SELECT DISTINCT job_id
                FROM job_events
                GROUP BY job_id, seq
                HAVING COUNT(*) > 1
            ),
            ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY job_id ORDER BY created_at, id
                       ) - 1 AS repaired_seq
                FROM job_events
                WHERE job_id IN (SELECT job_id FROM duplicate_jobs)
            )
            UPDATE job_events
            SET seq = (
                SELECT repaired_seq FROM ranked WHERE ranked.id = job_events.id
            )
            WHERE id IN (SELECT id FROM ranked)
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE jobs
            SET next_event_seq = COALESCE(
                (SELECT MAX(seq) + 1 FROM job_events WHERE job_events.job_id = jobs.id),
                0
            )
            """
        )
    )

    with op.batch_alter_table("job_events") as batch:
        batch.drop_index("ix_job_events_job_id")
        batch.create_unique_constraint(
            "uq_job_events_job_seq", ["job_id", "seq"]
        )
        batch.create_index(
            "ix_job_events_job_id_seq", ["job_id", "seq"], unique=False
        )
    logger.info("Atomic event migration repaired and indexed persisted events")


def downgrade() -> None:
    with op.batch_alter_table("job_events") as batch:
        batch.drop_index("ix_job_events_job_id_seq")
        batch.drop_constraint("uq_job_events_job_seq", type_="unique")
        batch.create_index("ix_job_events_job_id", ["job_id"], unique=False)
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("next_event_seq")
