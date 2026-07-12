from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.config import get_settings
from factory_api.db import get_db
from factory_api.models import Artifact, Project
from factory_api.schemas import ArtifactRead

router = APIRouter(prefix="/api", tags=["artifacts"])

DB = Annotated[Session, Depends(get_db)]

TEXT_FORMATS = {"markdown", "json", "text"}


def _check_owner(db: Session, user_id: str, artifact: Artifact | None) -> Artifact:
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artefacto no encontrado")
    project = db.get(Project, artifact.project_id)
    if project is None or project.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Artefacto no encontrado")
    return artifact


def _artifact_read(artifact: Artifact, include_content: bool) -> ArtifactRead:
    content = None
    if include_content and artifact.format in TEXT_FORMATS:
        path = get_settings().data_dir / artifact.path
        if path.is_file():
            content = path.read_text(encoding="utf-8")
    return ArtifactRead(
        id=artifact.id,
        project_id=artifact.project_id,
        type=artifact.type,
        format=artifact.format,
        title=artifact.title,
        created_by_job_id=artifact.created_by_job_id,
        created_at=artifact.created_at,
        content=content,
    )


@router.get("/projects/{project_id}/artifacts", response_model=list[ArtifactRead])
def list_project_artifacts(project_id: str, user: CurrentUser, db: DB):
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    artifacts = db.scalars(
        select(Artifact).where(Artifact.project_id == project_id).order_by(Artifact.created_at)
    ).all()
    return [_artifact_read(a, include_content=False) for a in artifacts]


@router.get("/artifacts/{artifact_id}", response_model=ArtifactRead)
def get_artifact(artifact_id: str, user: CurrentUser, db: DB):
    artifact = _check_owner(db, user.id, db.get(Artifact, artifact_id))
    return _artifact_read(artifact, include_content=True)


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, user: CurrentUser, db: DB):
    artifact = _check_owner(db, user.id, db.get(Artifact, artifact_id))
    path = get_settings().data_dir / artifact.path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichero no encontrado")
    return FileResponse(path, filename=path.name)
