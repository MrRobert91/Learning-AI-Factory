import io
import json
import logging
import re
import uuid
import zipfile
from pathlib import Path
from typing import Annotated

from factory_agents.tools.marp import available_renders, render_deck
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.artifact_versions import (
    add_artifact_version,
    artifact_metadata,
    select_artifact_version,
    select_latest_remaining,
)
from factory_api.auth import CurrentUser
from factory_api.config import get_settings
from factory_api.db import get_db
from factory_api.models import Artifact, Project
from factory_api.pdf_exports import LessonDocument, lessons_pdf
from factory_api.schemas import ArtifactEdit, ArtifactRead, ArtifactVersionRead

router = APIRouter(prefix="/api", tags=["artifacts"])
logger = logging.getLogger(__name__)

DB = Annotated[Session, Depends(get_db)]

TEXT_FORMATS = {"markdown", "json", "text"}
UPLOADABLE_TYPES = {
    "research_brief": "markdown",
    "course_plan": "json",
    "lesson_content": "markdown",
    "slide_deck": "markdown",
    "teaching_script": "markdown",
}


def _safe_filename(value: str, fallback: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return value[:100] or fallback


def _download_response(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _selected_artifacts(db: Session, project_id: str, type_: str) -> list[Artifact]:
    return list(
        db.scalars(
            select(Artifact)
            .where(
                Artifact.project_id == project_id,
                Artifact.type == type_,
                Artifact.is_selected.is_(True),
            )
            .order_by(Artifact.title, Artifact.created_at)
        ).all()
    )


def _artifact_documents(artifacts: list[Artifact]) -> list[LessonDocument]:
    settings = get_settings()
    documents = []
    for artifact in artifacts:
        path = settings.data_dir / artifact.path
        if path.is_file():
            documents.append(
                LessonDocument(
                    title=artifact.title or "Leccion",
                    markdown=path.read_text(encoding="utf-8"),
                )
            )
    return documents


def _ensure_slide_renders(path: Path) -> dict[str, str]:
    renders = available_renders(path)
    if len(renders) < 3:
        render_deck(path)
        renders = available_renders(path)
    return renders


def _marp_parts(markdown: str) -> tuple[str, str]:
    source = markdown.replace("\r\n", "\n").strip()
    if not source.startswith("---\n"):
        return "", source
    end = source.find("\n---", 4)
    if end == -1:
        return "", source
    after = source.find("\n", end + 4)
    return source[: end + 4], source[after + 1 :] if after != -1 else ""


def _combined_marp(artifacts: list[Artifact]) -> str:
    settings = get_settings()
    frontmatter = ""
    bodies: list[str] = []
    for artifact in artifacts:
        source = (settings.data_dir / artifact.path).read_text(encoding="utf-8")
        candidate_frontmatter, body = _marp_parts(source)
        if not frontmatter and candidate_frontmatter:
            frontmatter = candidate_frontmatter
        bodies.append(body.strip())
    if not frontmatter:
        frontmatter = "---\nmarp: true\ntheme: default\npaginate: true\n---"
    return frontmatter + "\n\n" + "\n\n---\n\n".join(bodies) + "\n"


def _render_combined_slides(artifacts: list[Artifact], fmt: str) -> bytes:
    settings = get_settings()
    export_dir = settings.data_dir / "tmp" / f"slides-{uuid.uuid4().hex}"
    export_dir.mkdir(parents=True, exist_ok=True)
    source = export_dir / "all-slides.md"
    source.write_text(_combined_marp(artifacts), encoding="utf-8")
    try:
        rendered = render_deck(source)
        target = rendered.get(fmt)
        if target is None:
            raise HTTPException(
                status_code=503,
                detail=f"No se pudo generar el fichero {fmt.upper()}; comprueba Marp CLI",
            )
        return Path(target).read_bytes()
    finally:
        for candidate in export_dir.glob("*"):
            candidate.unlink(missing_ok=True)
        export_dir.rmdir()


def _check_project(db: Session, user_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return project


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
    if artifact.type == "slide_deck":
        renders = sorted(available_renders(path))
    else:
        renders = ["pdf"] if artifact.type == "lesson_content" else []
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
        metadata=artifact_metadata(artifact),
        created_by_job_id=artifact.created_by_job_id,
        created_at=artifact.created_at,
        content=content,
        renders=renders,
        versions=[
            ArtifactVersionRead(
                id=item.id,
                version=item.version,
                is_selected=item.is_selected,
                metadata=artifact_metadata(item),
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


@router.patch("/artifacts/{artifact_id}", response_model=ArtifactRead)
def edit_artifact(
    artifact_id: str,
    body: ArtifactEdit,
    user: CurrentUser,
    db: DB,
):
    """Save edited text as the next immutable artifact version."""
    original = _check_owner(db, user.id, db.get(Artifact, artifact_id))
    if original.format not in TEXT_FORMATS:
        raise HTTPException(status_code=422, detail="Este formato no se puede editar como texto")
    if original.format == "json":
        try:
            json.loads(body.content)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"JSON invalido en la linea {exc.lineno}: {exc.msg}",
            ) from exc

    settings = get_settings()
    extension = (
        Path(original.path).suffix
        or {
            "markdown": ".md",
            "json": ".json",
            "text": ".txt",
        }[original.format]
    )
    relative = (
        f"artifacts/{original.project_id}/edit-{original.type}-{uuid.uuid4().hex[:10]}{extension}"
    )
    path = settings.data_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.content, encoding="utf-8")
    edited = add_artifact_version(
        db,
        project_id=original.project_id,
        type_=original.type,
        format_=original.format,
        title=original.title,
        path=relative,
        metadata=artifact_metadata(original),
    )
    db.commit()
    db.refresh(edited)
    if edited.type == "slide_deck":
        render_deck(path)
    logger.info(
        "Artifact version created from web editor",
        extra={
            "artifact_id": edited.id,
            "project_id": edited.project_id,
            "artifact_type": edited.type,
            "artifact_version": edited.version,
        },
    )
    return _artifact_read(db, edited, include_content=True)


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
            Path(candidate).unlink(missing_ok=True)
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
    path = get_settings().data_dir / artifact.path
    if artifact.type == "lesson_content":
        if fmt != "pdf" or not path.is_file():
            raise HTTPException(status_code=404, detail=f"Render {fmt} no disponible")
        content = lessons_pdf(
            [
                LessonDocument(
                    title=artifact.title or "Leccion",
                    markdown=path.read_text(encoding="utf-8"),
                )
            ]
        )
        logger.info(
            "Lesson PDF exported",
            extra={"artifact_id": artifact.id, "project_id": artifact.project_id},
        )
        return _download_response(
            content,
            "application/pdf",
            _safe_filename(artifact.title, "leccion") + ".pdf",
        )

    if artifact.type != "slide_deck" or fmt not in RENDER_MEDIA_TYPES:
        raise HTTPException(status_code=404, detail="Formato desconocido")
    renders = _ensure_slide_renders(path)
    if fmt not in renders:
        raise HTTPException(status_code=404, detail=f"Render {fmt} no disponible")
    logger.info(
        "Slide render downloaded",
        extra={
            "artifact_id": artifact.id,
            "project_id": artifact.project_id,
            "render_format": fmt,
        },
    )
    return FileResponse(
        renders[fmt],
        media_type=RENDER_MEDIA_TYPES[fmt],
        filename=f"{artifact.title}.{fmt}",
        content_disposition_type="inline" if fmt == "html" else "attachment",
    )


@router.get("/projects/{project_id}/exports/lessons.pdf")
def export_lessons_pdf(project_id: str, user: CurrentUser, db: DB):
    project = _check_project(db, user.id, project_id)
    documents = _artifact_documents(_selected_artifacts(db, project_id, "lesson_content"))
    if not documents:
        raise HTTPException(status_code=404, detail="No hay lecciones activas para exportar")
    content = lessons_pdf(documents)
    logger.info(
        "Combined lessons PDF exported",
        extra={"project_id": project_id, "artifact_count": len(documents)},
    )
    return _download_response(
        content,
        "application/pdf",
        _safe_filename(project.title, "curso") + "-lecciones.pdf",
    )


@router.get("/projects/{project_id}/exports/lessons.zip")
def export_lessons_zip(project_id: str, user: CurrentUser, db: DB):
    project = _check_project(db, user.id, project_id)
    documents = _artifact_documents(_selected_artifacts(db, project_id, "lesson_content"))
    if not documents:
        raise HTTPException(status_code=404, detail="No hay lecciones activas para exportar")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, document in enumerate(documents, start=1):
            name = f"{index:02d}-{_safe_filename(document.title, 'leccion')}.pdf"
            archive.writestr(name, lessons_pdf([document]))
    logger.info(
        "Lesson PDF ZIP exported",
        extra={"project_id": project_id, "artifact_count": len(documents)},
    )
    return _download_response(
        buffer.getvalue(),
        "application/zip",
        _safe_filename(project.title, "curso") + "-lecciones.zip",
    )


@router.get("/projects/{project_id}/exports/slides.pdf")
def export_slides_pdf(project_id: str, user: CurrentUser, db: DB):
    project = _check_project(db, user.id, project_id)
    artifacts = _selected_artifacts(db, project_id, "slide_deck")
    if not artifacts:
        raise HTTPException(status_code=404, detail="No hay slides activas para exportar")
    writer = PdfWriter()
    settings = get_settings()
    for artifact in artifacts:
        renders = _ensure_slide_renders(settings.data_dir / artifact.path)
        pdf_path = renders.get("pdf")
        if pdf_path is None:
            raise HTTPException(
                status_code=503,
                detail="No se pudieron renderizar todas las slides como PDF",
            )
        writer.append(PdfReader(pdf_path))
    buffer = io.BytesIO()
    writer.write(buffer)
    logger.info(
        "Combined slides PDF exported",
        extra={"project_id": project_id, "artifact_count": len(artifacts)},
    )
    return _download_response(
        buffer.getvalue(),
        "application/pdf",
        _safe_filename(project.title, "curso") + "-slides.pdf",
    )


@router.get("/projects/{project_id}/exports/slides.pptx")
def export_slides_pptx(project_id: str, user: CurrentUser, db: DB):
    project = _check_project(db, user.id, project_id)
    artifacts = _selected_artifacts(db, project_id, "slide_deck")
    if not artifacts:
        raise HTTPException(status_code=404, detail="No hay slides activas para exportar")
    content = _render_combined_slides(artifacts, "pptx")
    logger.info(
        "Combined slides PPTX exported",
        extra={"project_id": project_id, "artifact_count": len(artifacts)},
    )
    return _download_response(
        content,
        RENDER_MEDIA_TYPES["pptx"],
        _safe_filename(project.title, "curso") + "-slides.pptx",
    )


@router.get("/projects/{project_id}/exports/slides.zip")
def export_slides_zip(project_id: str, user: CurrentUser, db: DB):
    project = _check_project(db, user.id, project_id)
    artifacts = _selected_artifacts(db, project_id, "slide_deck")
    if not artifacts:
        raise HTTPException(status_code=404, detail="No hay slides activas para exportar")
    settings = get_settings()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, artifact in enumerate(artifacts, start=1):
            source = settings.data_dir / artifact.path
            renders = _ensure_slide_renders(source)
            stem = f"{index:02d}-{_safe_filename(artifact.title, 'slides')}"
            archive.write(source, f"{stem}.md")
            for fmt in ("pdf", "pptx"):
                if fmt in renders:
                    archive.write(renders[fmt], f"{stem}.{fmt}")
    logger.info(
        "Slides ZIP exported",
        extra={"project_id": project_id, "artifact_count": len(artifacts)},
    )
    return _download_response(
        buffer.getvalue(),
        "application/zip",
        _safe_filename(project.title, "curso") + "-slides.zip",
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
    if format_ == "json":
        try:
            json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail="El fichero JSON no es valido") from exc
    abs_path.write_bytes(data)
    artifact = add_artifact_version(
        db,
        project_id=project_id,
        type_=type,
        format_=format_,
        title=title or (file.filename or type),
        path=rel_path,
        metadata={
            "orientation": "horizontal",
            "width": 1920,
            "height": 1080,
        }
        if type == "slide_deck"
        else None,
    )
    db.commit()
    db.refresh(artifact)
    if type == "slide_deck":
        render_deck(abs_path)
    logger.info(
        "Artifact uploaded",
        extra={
            "artifact_id": artifact.id,
            "project_id": project_id,
            "artifact_type": type,
            "artifact_version": artifact.version,
        },
    )
    return _artifact_read(db, artifact, include_content=False)
