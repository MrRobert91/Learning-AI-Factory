"""Artifact version families and active selection.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-15
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

SINGLETON_TYPES = {"research_brief", "course_plan", "performance_report"}
TITLE_PREFIXES = (
    "Slides — ",
    "Guion — ",
    "Voz — ",
    "Vídeo — ",
    "Subtítulos — ",
    "Publicación — ",
    "Miniatura — ",
)


def _logical_key(type_: str, title: str) -> str:
    if type_ in SINGLETON_TYPES:
        return type_
    base = (title or type_).strip()
    for prefix in TITLE_PREFIXES:
        if base.startswith(prefix):
            base = base.removeprefix(prefix).strip()
            break
    match = re.match(r"^(\d+\.\d+)\b", base)
    return f"{type_}:{match.group(1) if match else base}"


def upgrade() -> None:
    op.add_column("artifacts", sa.Column("logical_key", sa.String(320), nullable=True))
    op.add_column(
        "artifacts",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "artifacts",
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, project_id, type, title FROM artifacts "
            "ORDER BY project_id, type, title, created_at, id"
        )
    ).mappings()
    groups: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        logical_key = _logical_key(row["type"], row["title"])
        connection.execute(
            sa.text("UPDATE artifacts SET logical_key = :key WHERE id = :id"),
            {"key": logical_key, "id": row["id"]},
        )
        groups.setdefault((row["project_id"], logical_key), []).append(row["id"])

    for ids in groups.values():
        for version, artifact_id in enumerate(ids, start=1):
            connection.execute(
                sa.text(
                    "UPDATE artifacts SET version = :version, is_selected = :selected "
                    "WHERE id = :id"
                ),
                {
                    "version": version,
                    "selected": version == len(ids),
                    "id": artifact_id,
                },
            )

    with op.batch_alter_table("artifacts") as batch:
        batch.alter_column("logical_key", existing_type=sa.String(320), nullable=False)
        batch.create_index(
            "ix_artifacts_project_logical_key",
            ["project_id", "logical_key"],
        )
        batch.create_unique_constraint(
            "uq_artifacts_project_key_version",
            ["project_id", "logical_key", "version"],
        )


def downgrade() -> None:
    with op.batch_alter_table("artifacts") as batch:
        batch.drop_constraint("uq_artifacts_project_key_version", type_="unique")
        batch.drop_index("ix_artifacts_project_logical_key")
        batch.drop_column("is_selected")
        batch.drop_column("version")
        batch.drop_column("logical_key")
