import uuid
from typing import Annotated

from factory_agents.tools.marp import available_renders
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.artifact_versions import (
    add_artifact_version,
    select_artifact_version,
    select_latest_remaining,
)
from factory_api.auth import CurrentUser
from factory_api.config import get_settings
from factory_api.db import get_db
from factory_api.models import Artifact, Project
from factory_api.schemas import ArtifactRead, ArtifactVersionRead

router = APIRouter(prefix="/api", tags=["artifacts"])

DB = Annotated[Session, Depends(get_db)]

TEXT_FORMATS = {"markdown", "json", "text"}
UPLOADABLE_TYPES = {
    "research_brief": "markdown",
    "course_plan": "json",
    "lesson_content": "markdown",
    "slide_deck": "markdown",
    "teaching_script": "markdown",
}


def pptx_to_marp(data: bytes) -> str:
    """Convert an uploaded PPTX to Marp Markdown (titles + text, best effort)."""
    from io import BytesIO

    from pptx import Presentation

    prs = Presentation(BytesIO(data))
    parts = ["---", "marp: true", "theme: default", "paginate: true", "---", ""]
    for i, slide in enumerate(prs.slides):
        if i > 0:
            parts.append("\n---\n")
        title = ""
        try:
            if slide.shapes.title is not None and slide.shapes.title.text.strip():
                title = slide.shapes.title.text.strip()
        except (AttributeError, KeyError):
            pass
        parts.append(f"## {title or f'Slide {i + 1}'}\n")
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            if title and shape is slide.shapes.title:
                continue
            for paragraph in shape.text_frame.paragraphs:
                text = "".join(run.text for run in paragraph.runs).strip()
                if text:
                    parts.append(f"- {text}")
    return "\n".join(parts) + "\n"
RENDER_MEDIA_TYPES = {
    "html": "text/html",
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _check_owner(db: Session, user_id: str, artifact: Artifact | None) -> Artifact:
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artefacto no encontrado")
    project = db.get(Project, artifact.project_id)
    if project is None or project.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Artefacto no encontrado")
    return artifact


def _artifact_read(db: Session, artifact: Artifact, include_content: bool) -> ArtifactRead:
    path = get_settings().data_dir / artifact.path
    content = None
    if include_content and artifact.format in TEXT_FORMATS and path.is_file():
        content = path.read_text(encoding="utf-8")
    renders = sorted(available_renders(path)) if artifact.type == "slide_deck" else []
    versions = db.scalars(
        select(Artifact)
        .where(
            Artifact.project_id == artifact.project_id,
            Artifact.logical_key == artifact.logical_key,
        )
        .order_by(Artifact.version.desc())
    ).all()
    return ArtifactRead(
        id=artifact.id,
        project_id=artifact.project_id,
        type=artifact.type,
        format=artifact.format,
        title=artifact.title,
        logical_key=artifact.logical_key,
        version=artifact.version,
        is_selected=artifact.is_selected,
        created_by_job_id=artifact.created_by_job_id,
        created_at=artifact.created_at,
        content=content,
        renders=renders,
        versions=[
            ArtifactVersionRead(
                id=item.id,
                version=item.version,
                is_selected=item.is_selected,
                created_at=item.created_at,
            )
            for item in versions
        ],
    )


@router.get("/projects/{project_id}/artifacts", response_model=list[ArtifactRead])
def list_project_artifacts(project_id: str, user: CurrentUser, db: DB):
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.is_selected.is_(True))
        .order_by(Artifact.created_at)
    ).all()
    return [_artifact_read(db, a, include_content=False) for a in artifacts]


@router.get("/artifacts/{artifact_id}", response_model=ArtifactRead)
def get_artifact(artifact_id: str, user: CurrentUser, db: DB):
    artifact = _check_owner(db, user.id, db.get(Artifact, artifact_id))
    return _artifact_read(db, artifact, include_content=True)


@router.post("/artifacts/{artifact_id}/select", response_model=ArtifactRead)
def select_artifact(artifact_id: str, user: CurrentUser, db: DB):
    artifact = _check_owner(db, user.id, db.get(Artifact, artifact_id))
    select_artifact_version(db, artifact)
    db.commit()
    db.refresh(artifact)
    return _artifact_read(db, artifact, include_content=False)


@router.delete("/artifacts/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_artifact(artifact_id: str, user: CurrentUser, db: DB):
    artifact = _check_owner(db, user.id, db.get(Artifact, artifact_id))
    path = get_settings().data_dir / artifact.path
    renders = available_renders(path) if artifact.type == "slide_deck" else {}
    if artifact.is_selected:
        select_latest_remaining(db, artifact)
    db.delete(artifact)
    db.commit()
    for candidate in [path, *renders.values()]:
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            # The DB deletion is authoritative; orphan cleanup is best effort.
            pass


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, user: CurrentUser, db: DB):
    artifact = _check_owner(db, user.id, db.get(Artifact, artifact_id))
    path = get_settings().data_dir / artifact.path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichero no encontrado")
    return FileResponse(path, filename=path.name)


@router.get("/artifacts/{artifact_id}/render/{fmt}")
def get_artifact_render(artifact_id: str, fmt: str, user: CurrentUser, db: DB):
    artifact = _check_owner(db, user.id, db.get(Artifact, artifact_id))
    if fmt not in RENDER_MEDIA_TYPES:
        raise HTTPException(status_code=404, detail="Formato desconocido")
    renders = available_renders(get_settings().data_dir / artifact.path)
    if fmt not in renders:
        raise HTTPException(status_code=404, detail=f"Render {fmt} no disponible")
    return FileResponse(
        renders[fmt], media_type=RENDER_MEDIA_TYPES[fmt], filename=f"{artifact.title}.{fmt}"
    )


@router.post(
    "/projects/{project_id}/artifacts",
    response_model=ArtifactRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_artifact(
    project_id: str,
    user: CurrentUser,
    db: DB,
    file: Annotated[UploadFile, File()],
    type: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
):
    """Entry point for external material (e.g. your own slides or notes)."""
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    if type not in UPLOADABLE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Tipo no subible. Permitidos: {', '.join(sorted(UPLOADABLE_TYPES))}",
        )
    settings = get_settings()
    format_ = UPLOADABLE_TYPES[type]
    ext = {"markdown": "md", "json": "json"}[format_]
    rel_path = f"artifacts/{project_id}/upload-{type}-{uuid.uuid4().hex[:8]}.{ext}"
    abs_path = settings.data_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    if type == "slide_deck" and (file.filename or "").lower().endswith(".pptx"):
        try:
            data = pptx_to_marp(data).encode("utf-8")
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"No se pudo convertir el PPTX: {exc}"
            ) from exc
    abs_path.write_bytes(data)
    artifact = add_artifact_version(
        db,
        project_id=project_id,
        type_=type,
        format_=format_,
        title=title or (file.filename or type),
        path=rel_path,
    )
    db.commit()
    db.refresh(artifact)
    return _artifact_read(db, artifact, include_content=False)
