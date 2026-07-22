import json
from typing import Annotated

from factory_agents import agents as _agents  # noqa: F401  (populate registry)
from factory_agents.runtime import REGISTRY
from factory_agents.tools.images import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_IMAGE_STYLE,
    IMAGE_MODEL_OPTIONS,
    IMAGE_STYLE_PRESETS,
    image_options,
)
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
ORIENTATION_AGENTS = {"slides", "video"}
IMAGE_CONFIG_KEYS = {
    "images_enabled",
    "image_model",
    "image_style",
    "image_style_prompt",
}


def _profile_config(
    agent_type: str,
    model: str | None,
    orientation: str | None,
    *,
    images_enabled: bool | None = None,
    image_model: str | None = None,
    image_style: str | None = None,
    image_style_prompt: str | None = None,
    automatic_review_enabled: bool | None = None,
    max_automatic_regenerations: int | None = None,
) -> dict:
    config = {
        "automatic_review_enabled": bool(automatic_review_enabled),
        "max_automatic_regenerations": max_automatic_regenerations or 0,
    }
    if model:
        config["model"] = model
    if agent_type in ORIENTATION_AGENTS:
        config["orientation"] = orientation or "horizontal"
    if agent_type == "slides":
        config.update(
            {
                "images_enabled": bool(images_enabled),
                "image_model": image_model or DEFAULT_IMAGE_MODEL,
                "image_style": image_style or DEFAULT_IMAGE_STYLE,
                "image_style_prompt": image_style_prompt or "",
            }
        )
    return config


def _slide_image_fields(config: dict, agent_type: str) -> dict:
    if agent_type != "slides":
        return {
            "images_enabled": None,
            "image_model": None,
            "image_style": None,
            "image_style_prompt": None,
        }
    return {
        "images_enabled": bool(config.get("images_enabled", False)),
        "image_model": config.get("image_model") or DEFAULT_IMAGE_MODEL,
        "image_style": config.get("image_style") or DEFAULT_IMAGE_STYLE,
        "image_style_prompt": config.get("image_style_prompt") or "",
    }


def _supplied_image_config(body: ProfileCreate | ProfileUpdate) -> dict:
    return {
        key: value
        for key, value in {
            "images_enabled": body.images_enabled,
            "image_model": body.image_model,
            "image_style": body.image_style,
            "image_style_prompt": body.image_style_prompt,
        }.items()
        if value is not None
    }


def _review_fields(config: dict) -> dict:
    return {
        "automatic_review_enabled": bool(config.get("automatic_review_enabled", False)),
        "max_automatic_regenerations": int(
            config.get("max_automatic_regenerations", 0) or 0
        ),
    }


def _validate_slide_image_config(agent_type: str, config: dict) -> None:
    if agent_type != "slides" and IMAGE_CONFIG_KEYS.intersection(config):
        raise HTTPException(
            status_code=422,
            detail="Solo el agente de Slides admite configuración de imágenes",
        )
    if agent_type != "slides":
        return
    if config.get("image_model", DEFAULT_IMAGE_MODEL) not in IMAGE_MODEL_OPTIONS:
        raise HTTPException(status_code=422, detail="Modelo de imágenes no permitido")
    style = config.get("image_style", DEFAULT_IMAGE_STYLE)
    if style not in IMAGE_STYLE_PRESETS:
        raise HTTPException(status_code=422, detail="Estilo de imágenes desconocido")
    if style == "custom" and not str(config.get("image_style_prompt", "")).strip():
        raise HTTPException(
            status_code=422,
            detail="El estilo personalizado necesita un prompt",
        )


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
                config_json=json.dumps(_profile_config(spec.name, None, None)),
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
        orientation=(config.get("orientation") or "horizontal")
        if p.agent_type in ORIENTATION_AGENTS
        else None,
        **_slide_image_fields(config, p.agent_type),
        **_review_fields(config),
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


@router.get("/image-options")
def get_image_options(user: CurrentUser):
    return image_options()


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
    supplied_images = _supplied_image_config(body)
    _validate_slide_image_config(agent_type, supplied_images)
    config = _profile_config(
        agent_type,
        body.model,
        body.orientation,
        images_enabled=body.images_enabled,
        image_model=body.image_model,
        image_style=body.image_style,
        image_style_prompt=body.image_style_prompt,
        automatic_review_enabled=body.automatic_review_enabled,
        max_automatic_regenerations=body.max_automatic_regenerations,
    )
    profile = AgentProfile(
        agent_type=agent_type,
        name=body.name,
        soul_md=body.soul_md,
        agents_md=body.agents_md,
        config_json=json.dumps(config, ensure_ascii=False),
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
    result = []
    for item in profile.versions:
        config = json.loads(item.config_json or "{}")
        result.append(
            ProfileVersionRead(
                version=item.version,
                soul_md=item.soul_md,
                agents_md=item.agents_md,
                model=config.get("model"),
                orientation=(config.get("orientation") or "horizontal")
                if profile.agent_type in ORIENTATION_AGENTS
                else None,
                **_slide_image_fields(config, profile.agent_type),
                **_review_fields(config),
                note=item.note,
                created_at=item.created_at,
            )
        )
    return result


@router.patch("/profiles/{profile_id}", response_model=ProfileRead)
def update_profile(profile_id: str, body: ProfileUpdate, user: CurrentUser, db: DB):
    profile = db.get(AgentProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")

    current_config = json.loads(profile.config_json or "{}")
    proposed_config = dict(current_config)
    supplied_images = _supplied_image_config(body)
    if supplied_images:
        _validate_slide_image_config(profile.agent_type, supplied_images)
        proposed_config.update(supplied_images)
    if body.model is not None:
        if body.model:
            proposed_config["model"] = body.model
        else:
            proposed_config.pop("model", None)
    if body.orientation is not None:
        if profile.agent_type not in ORIENTATION_AGENTS:
            raise HTTPException(
                status_code=422,
                detail="Este agente no admite configuración de orientación",
            )
        proposed_config["orientation"] = body.orientation
    if body.automatic_review_enabled is not None:
        proposed_config["automatic_review_enabled"] = body.automatic_review_enabled
    if body.max_automatic_regenerations is not None:
        proposed_config["max_automatic_regenerations"] = body.max_automatic_regenerations
    _validate_slide_image_config(profile.agent_type, proposed_config)

    content_changed = (
        (body.soul_md is not None and body.soul_md != profile.soul_md)
        or (body.agents_md is not None and body.agents_md != profile.agents_md)
        or proposed_config != current_config
    )
    if body.name is not None:
        profile.name = body.name
    if body.soul_md is not None:
        profile.soul_md = body.soul_md
    if body.agents_md is not None:
        profile.agents_md = body.agents_md
    if proposed_config != current_config:
        profile.config_json = json.dumps(proposed_config, ensure_ascii=False)
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
