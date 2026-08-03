"""Centralized ownership checks for job-scoped API operations."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.models import Job, Project


def get_owned_job(db: Session, user_id: str, job_id: str) -> Job:
    """Return a project-owned job or the same 404 for missing/foreign/global jobs."""

    job = db.scalar(
        select(Job)
        .join(Project, Job.project_id == Project.id)
        .where(Job.id == job_id, Project.owner_id == user_id)
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Ejecución no encontrada")
    return job
