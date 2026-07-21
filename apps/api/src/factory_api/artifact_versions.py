"""Helpers for versioned artifact families and their active selection."""

import json
import re

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from factory_api.models import Artifact

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


def artifact_logical_key(type_: str, title: str) -> str:
    """Stable identity: singleton by type, lesson assets by lesson number."""
    if type_ in SINGLETON_TYPES:
        return type_
    base = (title or type_).strip()
    for prefix in TITLE_PREFIXES:
        if base.startswith(prefix):
            base = base.removeprefix(prefix).strip()
            break
    lesson_number = re.match(r"^(\d+\.\d+)\b", base)
    identity = lesson_number.group(1) if lesson_number else base
    return f"{type_}:{identity}"


def add_artifact_version(
    db: Session,
    *,
    project_id: str,
    type_: str,
    format_: str,
    title: str,
    path: str,
    created_by_job_id: str | None = None,
    metadata: dict | None = None,
) -> Artifact:
    """Add and select the next version in a logical artifact family."""
    logical_key = artifact_logical_key(type_, title)
    previous = db.scalars(
        select(Artifact)
        .where(
            Artifact.project_id == project_id,
            Artifact.logical_key == logical_key,
        )
        .order_by(Artifact.version.desc())
    ).all()
    for artifact in previous:
        artifact.is_selected = False
    artifact = Artifact(
        project_id=project_id,
        type=type_,
        format=format_,
        title=title,
        logical_key=logical_key,
        version=(previous[0].version + 1) if previous else 1,
        is_selected=True,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        path=path,
        created_by_job_id=created_by_job_id,
    )
    db.add(artifact)
    db.flush()
    return artifact


def artifact_metadata(artifact: Artifact) -> dict:
    try:
        value = json.loads(artifact.metadata_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def selected_artifact(db: Session, project_id: str, type_: str) -> Artifact | None:
    return db.scalars(
        select(Artifact)
        .where(
            Artifact.project_id == project_id,
            Artifact.type == type_,
            Artifact.is_selected.is_(True),
        )
        .order_by(Artifact.created_at.desc())
        .limit(1)
    ).first()


def select_artifact_version(db: Session, artifact: Artifact) -> None:
    db.execute(
        update(Artifact)
        .where(
            Artifact.project_id == artifact.project_id,
            Artifact.logical_key == artifact.logical_key,
        )
        .values(is_selected=False)
    )
    artifact.is_selected = True


def select_latest_remaining(db: Session, artifact: Artifact) -> Artifact | None:
    replacement = db.scalars(
        select(Artifact)
        .where(
            Artifact.project_id == artifact.project_id,
            Artifact.logical_key == artifact.logical_key,
            Artifact.id != artifact.id,
        )
        .order_by(Artifact.version.desc())
        .limit(1)
    ).first()
    if replacement is not None:
        replacement.is_selected = True
    return replacement
