import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.db import get_db
from factory_api.models import (
    AgentProfileVersion,
    ImprovementProposal,
    Job,
    OAuthToken,
    Project,
    WikiPage,
)
from factory_api.routers.agents import get_default_profile
from factory_api.routers.runs import _job_read, _profile_fields
from factory_api.runner import runner
from factory_api.schemas import ImprovementProposalRead, JobRead

router = APIRouter(prefix="/api", tags=["improvements"])

DB = Annotated[Session, Depends(get_db)]


def _proposal_read(p: ImprovementProposal) -> ImprovementProposalRead:
    return ImprovementProposalRead(
        id=p.id,
        project_id=p.project_id,
        kind=p.kind,
        agent_type=p.agent_type,
        slug=p.slug,
        title=p.title,
        proposed_content=p.proposed_content,
        evidence=p.evidence,
        status=p.status,
        applied_profile_id=p.applied_profile_id,
        created_at=p.created_at,
    )


@router.post(
    "/projects/{project_id}/analytics-runs",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
)
def create_analytics_run(project_id: str, user: CurrentUser, db: DB):
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    token = db.scalars(
        select(OAuthToken).where(OAuthToken.provider == "google").limit(1)
    ).first()
    if token is None:
        raise HTTPException(
            status_code=409, detail="YouTube no está conectado: autoriza el acceso primero"
        )
    profile = get_default_profile(db, "analyst")
    payload = {
        "project_id": project.id,
        "project_title": project.title,
        **_profile_fields(profile),
    }
    job = Job(kind="analyst_run", project_id=project.id, payload_json=json.dumps(payload))
    db.add(job)
    db.commit()
    db.refresh(job)
    runner.enqueue(job.id)
    return _job_read(job)


@router.get("/improvements", response_model=list[ImprovementProposalRead])
def list_proposals(user: CurrentUser, db: DB, status_filter: str = "pending"):
    stmt = select(ImprovementProposal).order_by(ImprovementProposal.created_at.desc())
    if status_filter != "all":
        stmt = stmt.where(ImprovementProposal.status == status_filter)
    return [_proposal_read(p) for p in db.scalars(stmt).all()]


@router.post("/improvements/{proposal_id}/approve", response_model=ImprovementProposalRead)
def approve_proposal(proposal_id: str, user: CurrentUser, db: DB):
    proposal = db.get(ImprovementProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail="La propuesta ya fue revisada")

    if proposal.kind == "wiki":
        # Channel learnings live in the user-level wiki (main memory).
        page = db.scalars(
            select(WikiPage).where(
                WikiPage.project_id.is_(None), WikiPage.slug == proposal.slug
            )
        ).first()
        if page is None:
            page = WikiPage(
                project_id=None, slug=proposal.slug, title=proposal.title
            )
            db.add(page)
        page.title = proposal.title
        page.content_md = proposal.proposed_content
    elif proposal.kind == "agents_md":
        profile = get_default_profile(db, proposal.agent_type)
        if profile is None:
            raise HTTPException(
                status_code=409,
                detail=f"No hay perfil por defecto para {proposal.agent_type}",
            )
        profile.agents_md = proposal.proposed_content
        profile.version += 1
        db.add(
            AgentProfileVersion(
                profile_id=profile.id,
                version=profile.version,
                soul_md=profile.soul_md,
                agents_md=profile.agents_md,
                config_json=profile.config_json,
                note=f"Mejora continua: {proposal.title}"[:255],
            )
        )
        proposal.applied_profile_id = profile.id
    else:
        raise HTTPException(status_code=422, detail="Tipo de propuesta desconocido")

    proposal.status = "approved"
    db.commit()
    db.refresh(proposal)
    return _proposal_read(proposal)


@router.post("/improvements/{proposal_id}/reject", response_model=ImprovementProposalRead)
def reject_proposal(proposal_id: str, user: CurrentUser, db: DB):
    proposal = db.get(ImprovementProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail="La propuesta ya fue revisada")
    proposal.status = "rejected"
    db.commit()
    db.refresh(proposal)
    return _proposal_read(proposal)


def _current_agents_md(db: Session, agent_type: str) -> str:
    profile = get_default_profile(db, agent_type)
    return profile.agents_md if profile else ""


@router.get("/improvements/{proposal_id}/current")
def get_current_content(proposal_id: str, user: CurrentUser, db: DB):
    """Current content the proposal would replace (for the diff view)."""
    proposal = db.get(ImprovementProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Propuesta no encontrada")
    if proposal.kind == "agents_md":
        return {"current": _current_agents_md(db, proposal.agent_type)}
    page = db.scalars(
        select(WikiPage).where(
            WikiPage.project_id.is_(None), WikiPage.slug == proposal.slug
        )
    ).first()
    return {"current": page.content_md if page else ""}
