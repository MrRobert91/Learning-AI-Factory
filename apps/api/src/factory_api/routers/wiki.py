from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.db import get_db
from factory_api.models import Project, WikiPage
from factory_api.schemas import WikiPageRead, WikiPageWrite

router = APIRouter(prefix="/api", tags=["wiki"])

DB = Annotated[Session, Depends(get_db)]


def _check_project(db: Session, user_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return project


def _list_pages(db: Session, project_id: str | None) -> list[WikiPage]:
    condition = (
        WikiPage.project_id == project_id
        if project_id is not None
        else WikiPage.project_id.is_(None)
    )
    return list(db.scalars(select(WikiPage).where(condition).order_by(WikiPage.slug)).all())


def _upsert(db: Session, project_id: str | None, slug: str, body: WikiPageWrite) -> WikiPage:
    condition = (
        WikiPage.project_id == project_id
        if project_id is not None
        else WikiPage.project_id.is_(None)
    )
    page = db.scalars(select(WikiPage).where(condition, WikiPage.slug == slug)).first()
    if page is None:
        page = WikiPage(project_id=project_id, slug=slug, title=body.title or slug)
        db.add(page)
    if body.title:
        page.title = body.title
    page.content_md = body.content_md
    db.commit()
    db.refresh(page)
    return page


@router.get("/projects/{project_id}/wiki", response_model=list[WikiPageRead])
def list_project_wiki(project_id: str, user: CurrentUser, db: DB):
    _check_project(db, user.id, project_id)
    return _list_pages(db, project_id)


@router.put("/projects/{project_id}/wiki/{slug}", response_model=WikiPageRead)
def upsert_project_page(
    project_id: str, slug: str, body: WikiPageWrite, user: CurrentUser, db: DB
):
    _check_project(db, user.id, project_id)
    return _upsert(db, project_id, slug, body)


@router.delete(
    "/projects/{project_id}/wiki/{slug}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_project_page(project_id: str, slug: str, user: CurrentUser, db: DB):
    _check_project(db, user.id, project_id)
    page = db.scalars(
        select(WikiPage).where(WikiPage.project_id == project_id, WikiPage.slug == slug)
    ).first()
    if page is None:
        raise HTTPException(status_code=404, detail="Página no encontrada")
    db.delete(page)
    db.commit()


@router.get("/wiki", response_model=list[WikiPageRead])
def list_user_wiki(user: CurrentUser, db: DB):
    """User-level memory: preferences shared across projects."""
    return _list_pages(db, None)


@router.put("/wiki/{slug}", response_model=WikiPageRead)
def upsert_user_page(slug: str, body: WikiPageWrite, user: CurrentUser, db: DB):
    return _upsert(db, None, slug, body)
