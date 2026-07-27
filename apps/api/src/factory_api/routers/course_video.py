"""Authenticated API for deterministic full-course video exports."""

import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.course_video import build_preflight, public_preflight
from factory_api.db import get_db
from factory_api.models import Job, Project
from factory_api.routers.runs import _job_read
from factory_api.runner import runner
from factory_api.schemas import (
    CourseVideoCreate,
    CourseVideoPreflightRead,
    JobRead,
)

router = APIRouter(prefix="/api/projects", tags=["course-video"])
DB = Annotated[Session, Depends(get_db)]


def _project(db: Session, user_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return project


@router.get(
    "/{project_id}/course-video/preflight",
    response_model=CourseVideoPreflightRead,
)
def course_video_preflight(
    project_id: str,
    user: CurrentUser,
    db: DB,
    include_subtitles: bool | None = Query(default=None),
    include_chapters: bool = Query(default=True),
    transition: Literal["none", "fade_500ms", "gap_500ms"] = Query(default="none"),
):
    project = _project(db, user.id, project_id)
    return public_preflight(
        build_preflight(
            db,
            project,
            include_subtitles=include_subtitles,
            include_chapters=include_chapters,
            transition=transition,
        )
    )


@router.post(
    "/{project_id}/course-video",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
)
def create_course_video(
    project_id: str,
    body: CourseVideoCreate,
    user: CurrentUser,
    db: DB,
):
    project = _project(db, user.id, project_id)
    preflight = build_preflight(
        db,
        project,
        include_subtitles=body.include_subtitles,
        include_chapters=body.include_chapters,
        transition=body.transition,
    )
    public = public_preflight(preflight)
    if not public["ready"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "El preflight del vídeo completo ha fallado.",
                "issues": public["issues"],
            },
        )
    payload = {
        "project_id": project.id,
        "project_title": project.title,
        "include_subtitles": body.include_subtitles,
        "include_chapters": body.include_chapters,
        "transition": body.transition,
        "expected_input_signature": public["input_signature"],
    }
    job = Job(
        kind="course_video_export",
        project_id=project.id,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    runner.enqueue(job.id)
    return _job_read(job)
