from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.db import get_db
from factory_api.models import Project
from factory_api.schemas import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])

DB = Annotated[Session, Depends(get_db)]


def _get_owned_project(db: Session, user_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Proyecto no encontrado"
        )
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(user: CurrentUser, db: DB):
    stmt = (
        select(Project)
        .where(Project.owner_id == user.id)
        .order_by(Project.updated_at.desc())
    )
    return db.scalars(stmt).all()


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, user: CurrentUser, db: DB):
    project = Project(owner_id=user.id, **body.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, user: CurrentUser, db: DB):
    return _get_owned_project(db, user.id, project_id)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(project_id: str, body: ProjectUpdate, user: CurrentUser, db: DB):
    project = _get_owned_project(db, user.id, project_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, user: CurrentUser, db: DB):
    project = _get_owned_project(db, user.id, project_id)
    db.delete(project)
    db.commit()
