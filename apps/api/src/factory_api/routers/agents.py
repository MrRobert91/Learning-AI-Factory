import json
from typing import Annotated

from factory_agents import agents as _agents  # noqa: F401  (populate registry)
from factory_agents.runtime import REGISTRY
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.db import get_db
from factory_api.models import AgentProfile, AgentProfileVersion
from factory_api.schemas import (
    AgentSpecRead,
    ProfileCreate,
    ProfileRead,
    ProfileUpdate,
    ProfileVersionRead,
)

router = APIRouter(prefix="/api/agents", tags=["agents"])

DB = Annotated[Session, Depends(get_db)]


def seed_default_profiles(db: Session) -> None:
    """Create the factory default profile for any agent type missing one."""
    for spec in REGISTRY.values():
        exists = db.scalars(
            select(AgentProfile).where(AgentProfile.agent_type == spec.name).limit(1)
        ).first()
        if exists is None:
            profile = AgentProfile(
                agent_type=spec.name,
                name=f"{spec.display_name} (por defecto)",
                soul_md=spec.default_soul_md,
                agents_md=spec.default_agents_md,
                is_default=True,
            )
            db.add(profile)
            db.flush()
            db.add(
                AgentProfileVersion(
                    profile_id=profile.id,
                    version=1,
                    soul_md=profile.soul_md,
                    agents_md=profile.agents_md,
                    config_json=profile.config_json,
                    note="Perfil de fábrica",
                )
            )
    db.commit()


def _profile_read(p: AgentProfile) -> ProfileRead:
    config = json.loads(p.config_json or "{}")
    return ProfileRead(
        id=p.id,
        agent_type=p.agent_type,
        name=p.name,
        soul_md=p.soul_md,
        agents_md=p.agents_md,
        model=config.get("model"),
        version=p.version,
        is_default=p.is_default,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def get_default_profile(db: Session, agent_type: str) -> AgentProfile | None:
    profile = db.scalars(
        select(AgentProfile)
        .where(AgentProfile.agent_type == agent_type, AgentProfile.is_default.is_(True))
        .limit(1)
    ).first()
    if profile is None:
        profile = db.scalars(
            select(AgentProfile).where(AgentProfile.agent_type == agent_type).limit(1)
        ).first()
    return profile


@router.get("", response_model=list[AgentSpecRead])
def list_agents(user: CurrentUser):
    return [
        AgentSpecRead(
            name=s.name,
            display_name=s.display_name,
            description=s.description,
            kind=s.kind,
            tool_names=list(s.tool_names),
            consumes=list(s.consumes),
            produces=list(s.produces),
        )
        for s in REGISTRY.values()
    ]


@router.get("/{agent_type}/profiles", response_model=list[ProfileRead])
def list_profiles(agent_type: str, user: CurrentUser, db: DB):
    if agent_type not in REGISTRY:
        raise HTTPException(status_code=404, detail="Agente desconocido")
    profiles = db.scalars(
        select(AgentProfile)
        .where(AgentProfile.agent_type == agent_type)
        .order_by(AgentProfile.created_at)
    ).all()
    return [_profile_read(p) for p in profiles]


@router.post(
    "/{agent_type}/profiles", response_model=ProfileRead, status_code=status.HTTP_201_CREATED
)
def create_profile(agent_type: str, body: ProfileCreate, user: CurrentUser, db: DB):
    if agent_type not in REGISTRY:
        raise HTTPException(status_code=404, detail="Agente desconocido")
    config = {"model": body.model} if body.model else {}
    profile = AgentProfile(
        agent_type=agent_type,
        name=body.name,
        soul_md=body.soul_md,
        agents_md=body.agents_md,
        config_json=json.dumps(config),
    )
    db.add(profile)
    db.flush()
    db.add(
        AgentProfileVersion(
            profile_id=profile.id,
            version=1,
            soul_md=profile.soul_md,
            agents_md=profile.agents_md,
            config_json=profile.config_json,
            note="Creación",
        )
    )
    db.commit()
    db.refresh(profile)
    return _profile_read(profile)


@router.get("/profiles/{profile_id}", response_model=ProfileRead)
def get_profile(profile_id: str, user: CurrentUser, db: DB):
    profile = db.get(AgentProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return _profile_read(profile)


@router.get("/profiles/{profile_id}/versions", response_model=list[ProfileVersionRead])
def list_profile_versions(profile_id: str, user: CurrentUser, db: DB):
    profile = db.get(AgentProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    return profile.versions


@router.patch("/profiles/{profile_id}", response_model=ProfileRead)
def update_profile(profile_id: str, body: ProfileUpdate, user: CurrentUser, db: DB):
    profile = db.get(AgentProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")

    content_changed = (
        (body.soul_md is not None and body.soul_md != profile.soul_md)
        or (body.agents_md is not None and body.agents_md != profile.agents_md)
        or (body.model is not None)
    )
    if body.name is not None:
        profile.name = body.name
    if body.soul_md is not None:
        profile.soul_md = body.soul_md
    if body.agents_md is not None:
        profile.agents_md = body.agents_md
    if body.model is not None:
        config = json.loads(profile.config_json or "{}")
        config["model"] = body.model or None
        profile.config_json = json.dumps({k: v for k, v in config.items() if v})
    if body.is_default is True:
        for other in db.scalars(
            select(AgentProfile).where(AgentProfile.agent_type == profile.agent_type)
        ).all():
            other.is_default = other.id == profile.id
    if content_changed:
        profile.version += 1
        db.add(
            AgentProfileVersion(
                profile_id=profile.id,
                version=profile.version,
                soul_md=profile.soul_md,
                agents_md=profile.agents_md,
                config_json=profile.config_json,
                note=body.note,
            )
        )
    db.commit()
    db.refresh(profile)
    return _profile_read(profile)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: str, user: CurrentUser, db: DB):
    profile = db.get(AgentProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    if profile.is_default:
        raise HTTPException(status_code=409, detail="No se puede borrar el perfil por defecto")
    db.delete(profile)
    db.commit()
