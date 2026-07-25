import json
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from factory_agents import agents as _agents  # noqa: F401  (populate registry)
from factory_agents.runtime import REGISTRY
from factory_agents.tools.images import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_IMAGE_STYLE,
    IMAGE_MODEL_OPTIONS,
    IMAGE_STYLE_PRESETS,
    ImageGenerationError,
    generate_image,
    image_options,
    media_extension,
)
from factory_agents.tools.palette import (
    normalize_palette,
    palette_options,
)
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.config import get_settings
from factory_api.db import get_db
from factory_api.logo_assets import (
    MAX_LOGO_BYTES,
    LogoValidationError,
    remove_logo_files,
    remove_profile_logo_files,
    store_logo,
    stored_logo_path,
    validate_logo,
)
from factory_api.models import AgentProfile, AgentProfileVersion, Artifact
from factory_api.schemas import (
    AgentSpecRead,
    LogoGenerateRequest,
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
LOGO_CONFIG_KEYS = {
    "logo_mode",
    "active_logo_id",
    "logo_placement",
    "logo_size",
    "logo_margin_px",
    "logo_opacity",
    "logo_visibility",
}
DEFAULT_LOGO_VISIBILITY = {"cover": True, "content": True, "summary": True}


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
    human_review_enabled: bool | None = None,
    slide_palette: dict[str, str] | None = None,
    logo_mode: str | None = None,
    active_logo_id: str | None = None,
    logo_placement: str | None = None,
    logo_size: str | None = None,
    logo_margin_px: int | None = None,
    logo_opacity: float | None = None,
    logo_visibility: dict[str, bool] | None = None,
) -> dict:
    config = {
        "automatic_review_enabled": bool(automatic_review_enabled),
        "max_automatic_regenerations": max_automatic_regenerations or 0,
        "human_review_enabled": bool(human_review_enabled),
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
                "slide_palette": normalize_palette(slide_palette),
                "logo_mode": logo_mode or "none",
                "active_logo_id": active_logo_id,
                "logo_placement": logo_placement or "top-right",
                "logo_size": logo_size or "small",
                "logo_margin_px": 32 if logo_margin_px is None else logo_margin_px,
                "logo_opacity": 1.0 if logo_opacity is None else logo_opacity,
                "logo_visibility": logo_visibility or dict(DEFAULT_LOGO_VISIBILITY),
                "logo_candidates": [],
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


def _slide_palette_field(config: dict, agent_type: str) -> dict:
    return {
        "slide_palette": normalize_palette(config.get("slide_palette"))
        if agent_type == "slides"
        else None
    }


def _slide_logo_fields(config: dict, agent_type: str) -> dict:
    if agent_type != "slides":
        return {
            "logo_mode": None,
            "active_logo_id": None,
            "logo_placement": None,
            "logo_size": None,
            "logo_margin_px": None,
            "logo_opacity": None,
            "logo_visibility": None,
            "logo_candidates": None,
        }
    return {
        "logo_mode": config.get("logo_mode") or "none",
        "active_logo_id": config.get("active_logo_id"),
        "logo_placement": config.get("logo_placement") or "top-right",
        "logo_size": config.get("logo_size") or "small",
        "logo_margin_px": int(config.get("logo_margin_px", 32)),
        "logo_opacity": float(config.get("logo_opacity", 1.0)),
        "logo_visibility": config.get("logo_visibility") or dict(DEFAULT_LOGO_VISIBILITY),
        "logo_candidates": config.get("logo_candidates") or [],
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


def _supplied_logo_config(body: ProfileCreate | ProfileUpdate) -> dict:
    supplied = {}
    for key in LOGO_CONFIG_KEYS:
        if key not in body.model_fields_set:
            continue
        value = getattr(body, key)
        supplied[key] = value.model_dump() if key == "logo_visibility" and value else value
    return supplied


def _review_fields(config: dict) -> dict:
    return {
        "automatic_review_enabled": bool(config.get("automatic_review_enabled", False)),
        "max_automatic_regenerations": int(
            config.get("max_automatic_regenerations", 0) or 0
        ),
        "human_review_enabled": bool(config.get("human_review_enabled", False)),
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
        raise HTTPException(status_code=422, detail="Modelo de im\u00e1genes no permitido")
    style = config.get("image_style", DEFAULT_IMAGE_STYLE)
    if style not in IMAGE_STYLE_PRESETS:
        raise HTTPException(status_code=422, detail="Estilo de im\u00e1genes desconocido")
    if style == "custom" and not str(config.get("image_style_prompt", "")).strip():
        raise HTTPException(
            status_code=422,
            detail="El estilo personalizado necesita un prompt",
        )


def _validate_slide_logo_config(agent_type: str, config: dict) -> None:
    if agent_type != "slides" and LOGO_CONFIG_KEYS.intersection(config):
        raise HTTPException(
            status_code=422,
            detail="Solo el agente de Slides admite configuraci\u00f3n de logo",
        )
    if agent_type != "slides":
        return
    mode = config.get("logo_mode", "none")
    active_id = config.get("active_logo_id")
    candidates = config.get("logo_candidates") or []
    candidate = next((item for item in candidates if item.get("id") == active_id), None)
    if mode == "none":
        return
    visibility = config.get("logo_visibility") or DEFAULT_LOGO_VISIBILITY
    if not any(bool(value) for value in visibility.values()):
        raise HTTPException(
            status_code=422,
            detail="El logo debe estar visible al menos en un tipo de slide",
        )
    if candidate is None or candidate.get("status") != "available":
        raise HTTPException(status_code=422, detail="Selecciona un logo disponible")
    if candidate.get("source") != mode:
        raise HTTPException(
            status_code=422,
            detail="El modo del logo no coincide con el origen del candidato activo",
        )


def _normalize_supplied_palette(
    agent_type: str, palette: dict[str, str] | None
) -> dict[str, str] | None:
    if palette is None:
        return None
    if agent_type != "slides":
        raise HTTPException(
            status_code=422,
            detail="Solo el agente de Slides admite configuración de paleta",
        )
    try:
        return normalize_palette(palette)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
        **_slide_palette_field(config, p.agent_type),
        **_slide_logo_fields(config, p.agent_type),
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


@router.get("/palette-options")
def get_palette_options(user: CurrentUser):
    return palette_options()


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
    slide_palette = _normalize_supplied_palette(agent_type, body.slide_palette)
    supplied_logo = _supplied_logo_config(body)
    _validate_slide_logo_config(agent_type, supplied_logo)
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
        human_review_enabled=body.human_review_enabled,
        slide_palette=slide_palette,
        logo_mode=body.logo_mode,
        active_logo_id=body.active_logo_id,
        logo_placement=body.logo_placement,
        logo_size=body.logo_size,
        logo_margin_px=body.logo_margin_px,
        logo_opacity=body.logo_opacity,
        logo_visibility=body.logo_visibility.model_dump() if body.logo_visibility else None,
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
                **_slide_palette_field(config, profile.agent_type),
                **_slide_logo_fields(config, profile.agent_type),
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
    slide_palette = _normalize_supplied_palette(profile.agent_type, body.slide_palette)
    if slide_palette is not None:
        proposed_config["slide_palette"] = slide_palette
    supplied_logo = _supplied_logo_config(body)
    if supplied_logo:
        if profile.agent_type != "slides":
            raise HTTPException(
                status_code=422,
                detail="Solo el agente de Slides admite configuraci\u00f3n de logo",
            )
        proposed_config.update(supplied_logo)
        if proposed_config.get("logo_mode") == "none":
            proposed_config["active_logo_id"] = None
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
    if body.human_review_enabled is not None:
        proposed_config["human_review_enabled"] = body.human_review_enabled
    _validate_slide_image_config(profile.agent_type, proposed_config)
    _validate_slide_logo_config(profile.agent_type, proposed_config)

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


def _slides_profile(db: Session, profile_id: str) -> AgentProfile:
    profile = db.get(AgentProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    if profile.agent_type != "slides":
        raise HTTPException(status_code=422, detail="El perfil no pertenece a Slides")
    return profile


def _save_logo_candidate(
    db: Session, profile: AgentProfile, candidate: dict, *, note: str
) -> ProfileRead:
    config = json.loads(profile.config_json or "{}")
    config.setdefault("logo_candidates", []).append(candidate)
    profile.config_json = json.dumps(config, ensure_ascii=False)
    profile.version += 1
    db.add(
        AgentProfileVersion(
            profile_id=profile.id,
            version=profile.version,
            soul_md=profile.soul_md,
            agents_md=profile.agents_md,
            config_json=profile.config_json,
            note=note,
        )
    )
    db.commit()
    db.refresh(profile)
    return _profile_read(profile)


def _candidate(config: dict, logo_id: str) -> dict | None:
    return next(
        (item for item in config.get("logo_candidates", []) if item.get("id") == logo_id),
        None,
    )


@router.post("/profiles/{profile_id}/logos/upload", response_model=ProfileRead)
async def upload_profile_logo(
    profile_id: str,
    user: CurrentUser,
    db: DB,
    file: Annotated[UploadFile, File()],
    name: Annotated[str, Form()] = "",
):
    profile = _slides_profile(db, profile_id)
    content = await file.read(MAX_LOGO_BYTES + 1)
    try:
        validated = validate_logo(content, file.filename or "", file.content_type or "")
    except LogoValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logo_id = f"logo-{uuid.uuid4().hex[:12]}"
    try:
        path, thumbnail_path = store_logo(profile.id, logo_id, validated)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="No se pudo guardar el logo") from exc
    candidate = {
        "id": logo_id,
        "source": "uploaded",
        "name": name.strip() or Path(file.filename or "Logo subido").stem,
        "path": path,
        "thumbnail_path": thumbnail_path,
        "media_type": validated.media_type,
        "width": validated.width,
        "height": validated.height,
        "sha256": validated.sha256,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "available",
    }
    return _save_logo_candidate(db, profile, candidate, note="Logo subido")


@router.post("/profiles/{profile_id}/logos/generate", response_model=ProfileRead)
def generate_profile_logo(
    profile_id: str, body: LogoGenerateRequest, user: CurrentUser, db: DB
):
    profile = _slides_profile(db, profile_id)
    config = json.loads(profile.config_json or "{}")
    model = body.model or config.get("image_model") or DEFAULT_IMAGE_MODEL
    if model not in IMAGE_MODEL_OPTIONS:
        raise HTTPException(status_code=422, detail="Modelo de im\u00e1genes no permitido")
    seed = secrets.randbelow(2**31)
    resolved_prompt = (
        f"{body.prompt.strip()}\n\nCreate one clean brand logo on a transparent or plain "
        "background, centered with generous safe space. No mockup, frame, watermark, or UI."
    )
    try:
        generated = generate_image(
            resolved_prompt,
            api_key=get_settings().openrouter_api_key,
            model=model,
            orientation="horizontal",
            seed=seed,
        )
        extension = media_extension(generated.media_type, generated.content)
        validated = validate_logo(
            generated.content,
            f"generated{extension}",
            generated.media_type,
        )
    except (ImageGenerationError, LogoValidationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    logo_id = f"logo-{uuid.uuid4().hex[:12]}"
    try:
        path, thumbnail_path = store_logo(profile.id, logo_id, validated)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="No se pudo guardar el logo") from exc
    candidate = {
        "id": logo_id,
        "source": "generated",
        "name": body.name.strip() or "Logo generado",
        "path": path,
        "thumbnail_path": thumbnail_path,
        "media_type": validated.media_type,
        "width": validated.width,
        "height": validated.height,
        "sha256": validated.sha256,
        "prompt": body.prompt.strip(),
        "model": model,
        "seed": seed if IMAGE_MODEL_OPTIONS[model]["supports_seed"] else None,
        "cost_usd": generated.cost_usd,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "available",
    }
    return _save_logo_candidate(db, profile, candidate, note="Logo generado")


@router.get("/profiles/{profile_id}/logos/{logo_id}")
def get_profile_logo(
    profile_id: str,
    logo_id: str,
    user: CurrentUser,
    db: DB,
    thumbnail: bool = False,
):
    profile = _slides_profile(db, profile_id)
    config = json.loads(profile.config_json or "{}")
    candidate = _candidate(config, logo_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Logo no encontrado")
    relative_path = candidate.get("thumbnail_path" if thumbnail else "path", "")
    path = stored_logo_path(str(relative_path))
    if path is None:
        raise HTTPException(status_code=404, detail="El archivo del logo no est\u00e1 disponible")
    media_type = (
        candidate.get("media_type")
        if not thumbnail or candidate.get("media_type") == "image/svg+xml"
        else "image/png"
    )
    return FileResponse(path, media_type=media_type)


@router.delete(
    "/profiles/{profile_id}/logos/{logo_id}",
    response_model=ProfileRead,
)
def delete_profile_logo(profile_id: str, logo_id: str, user: CurrentUser, db: DB):
    profile = _slides_profile(db, profile_id)
    config = json.loads(profile.config_json or "{}")
    candidate = _candidate(config, logo_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Logo no encontrado")
    for version in profile.versions:
        version_config = json.loads(version.config_json or "{}")
        if version_config.get("active_logo_id") == logo_id:
            raise HTTPException(
                status_code=409,
                detail="No se puede eliminar un logo referenciado por una versi\u00f3n del perfil",
            )
    artifacts = db.scalars(
        select(Artifact).where(Artifact.type == "slide_deck")
    ).all()
    if any(
        (json.loads(item.metadata_json or "{}").get("logo") or {}).get("source_logo_id")
        == logo_id
        for item in artifacts
    ):
        raise HTTPException(
            status_code=409,
            detail="No se puede eliminar un logo referenciado por un artefacto",
        )
    config["logo_candidates"] = [
        item for item in config.get("logo_candidates", []) if item.get("id") != logo_id
    ]
    profile.config_json = json.dumps(config, ensure_ascii=False)
    profile.version += 1
    db.add(
        AgentProfileVersion(
            profile_id=profile.id,
            version=profile.version,
            soul_md=profile.soul_md,
            agents_md=profile.agents_md,
            config_json=profile.config_json,
            note="Logo eliminado",
        )
    )
    db.commit()
    remove_logo_files(profile.id, logo_id)
    db.refresh(profile)
    return _profile_read(profile)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: str, user: CurrentUser, db: DB):
    profile = db.get(AgentProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Perfil no encontrado")
    if profile.is_default:
        raise HTTPException(status_code=409, detail="No se puede borrar el perfil por defecto")
    deleted_profile_id = profile.id
    db.delete(profile)
    db.commit()
    remove_profile_logo_files(deleted_profile_id)
