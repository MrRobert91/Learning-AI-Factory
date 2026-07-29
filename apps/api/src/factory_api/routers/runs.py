import asyncio
import json
from typing import Annotated

from factory_agents.agents.curator import render_curator_input
from factory_agents.contracts.agent_io import AGENT_OUTPUTS
from factory_agents.tools.images import DEFAULT_IMAGE_MODEL, DEFAULT_IMAGE_STYLE
from factory_agents.tools.palette import DEFAULT_SLIDE_PALETTE, normalize_palette
from factory_agents.tools.tts import default_tts_config, resolve_tts_config
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.db import SessionLocal, get_db
from factory_api.models import AgentProfile, Artifact, IdeationSession, Job, JobEvent, Project
from factory_api.routers.agents import get_default_profile
from factory_api.run_control import SSE_STOP_STATUSES, load_control
from factory_api.runner import runner
from factory_api.schemas import AgentRunCreate, JobEventRead, JobRead
from factory_api.usage import job_usage_summary
from factory_api.workflow_engine import missing_agent_inputs

router = APIRouter(prefix="/api", tags=["runs"])

DB = Annotated[Session, Depends(get_db)]


def _event_read(e: JobEvent) -> JobEventRead:
    return JobEventRead(
        seq=e.seq,
        type=e.type,
        summary=e.summary,
        data=json.loads(e.data_json) if e.data_json else None,
        created_at=e.created_at,
    )


def _job_read(job: Job, include_events: bool = True) -> JobRead:
    payload = json.loads(job.payload_json or "{}")
    review_policies: dict[str, dict] = {}
    if job.kind == "workflow_run":
        for step in payload.get("definition", {}).get("steps", []):
            overrides = step.get("overrides", {})
            review_policies[step.get("agent", "")] = {
                "enabled": bool(overrides.get("automatic_review_enabled", False)),
                "max_regenerations": int(
                    overrides.get("max_automatic_regenerations", 0) or 0
                ),
                "profile_id": overrides.get("profile_id"),
                "profile_version": overrides.get("profile_version"),
                "evaluator_model": overrides.get("evaluator_model"),
                "human_review_enabled": bool(
                    overrides.get("human_review_enabled", False)
                ),
            }
    elif job.kind == "pipeline_run":
        for agent, fields in payload.get("stages", {}).items():
            review_policies[agent] = {
                "enabled": bool(fields.get("automatic_review_enabled", False)),
                "max_regenerations": int(
                    fields.get("max_automatic_regenerations", 0) or 0
                ),
                "profile_id": fields.get("profile_id"),
                "profile_version": fields.get("profile_version"),
                "evaluator_model": fields.get("evaluator_model"),
                "human_review_enabled": bool(
                    fields.get("human_review_enabled", False)
                ),
            }
    elif job.kind.endswith("_run"):
        agent = job.kind.removesuffix("_run")
        review_policies[agent] = {
            "enabled": bool(payload.get("automatic_review_enabled", False)),
            "max_regenerations": int(payload.get("max_automatic_regenerations", 0) or 0),
            "profile_id": payload.get("profile_id"),
            "profile_version": payload.get("profile_version"),
            "evaluator_model": payload.get("evaluator_model"),
            "human_review_enabled": bool(payload.get("human_review_enabled", False)),
        }
    with SessionLocal() as usage_db:
        usage_summary = job_usage_summary(usage_db, job.id)
    return JobRead(
        id=job.id,
        kind=job.kind,
        status=job.status,
        error=job.error,
        project_id=job.project_id,
        workflow_id=payload.get("workflow_id"),
        workflow_name=payload.get("workflow_name"),
        result=json.loads(job.result_json) if job.result_json else None,
        control=load_control(job),
        usage_summary=usage_summary,
        review_policies=review_policies,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        events=[_event_read(e) for e in job.events] if include_events else [],
    )


RUNNABLE_AGENTS = (
    "curator",
    "planner",
    "lessons",
    "slides",
    "script",
    "voice",
    "video",
    "publisher",
)
ACTIVE_PROJECT_JOB_STATUSES = (
    "queued",
    "running",
    "pausing",
    "paused",
    "waiting_approval",
    "canceling",
)


def _selected_artifact_ids(db: Session, project_id: str) -> dict[str, list[str]]:
    artifacts = db.scalars(
        select(Artifact)
        .where(
            Artifact.project_id == project_id,
            Artifact.is_selected.is_(True),
        )
        .order_by(Artifact.created_at, Artifact.id)
    ).all()
    selected: dict[str, list[str]] = {}
    for artifact in artifacts:
        selected.setdefault(artifact.type, []).append(artifact.id)
    return selected


def _idempotent_project_job(
    db: Session,
    project_id: str,
    request_id: str | None,
    *,
    kind: str,
) -> Job | None:
    if not request_id:
        return None
    jobs = db.scalars(
        select(Job)
        .where(Job.project_id == project_id)
        .order_by(Job.created_at.desc())
        .limit(50)
    ).all()
    for job in jobs:
        try:
            payload = json.loads(job.payload_json or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if job.kind == kind and payload.get("request_id") == request_id:
            return job
    return None


def _begin_serialized_job_creation(db: Session) -> None:
    """Serialize the check-and-create sequence in the project's SQLite database."""
    db.execute(text("BEGIN IMMEDIATE"))


def _ensure_project_has_no_active_job(db: Session, project_id: str) -> None:
    active = db.scalars(
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.status.in_(ACTIVE_PROJECT_JOB_STATUSES),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    ).first()
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Ya existe una ejecución activa incompatible para este proyecto: "
                f"{active.kind} ({active.status}, job {active.id[:8]})."
            ),
        )


def _profile_fields(profile: AgentProfile | None) -> dict:
    from factory_api.config import get_settings

    evaluator_model = get_settings().openrouter_model
    if profile is None:
        return {
            "soul_md": "",
            "agents_md": "",
            "model": None,
            "orientation": "horizontal",
            "images_enabled": False,
            "image_model": DEFAULT_IMAGE_MODEL,
            "image_style": DEFAULT_IMAGE_STYLE,
            "image_style_prompt": "",
            "profile_id": None,
            "profile_version": None,
            "automatic_review_enabled": False,
            "max_automatic_regenerations": 0,
            "human_review_enabled": False,
            "evaluator_model": evaluator_model,
            "slide_palette": dict(DEFAULT_SLIDE_PALETTE),
            "slide_logo": None,
            "tts_config": None,
            "subtitles_mode": "none",
        }
    config = json.loads(profile.config_json or "{}")
    active_logo_id = config.get("active_logo_id")
    logo_candidate = next(
        (
            item
            for item in config.get("logo_candidates", [])
            if item.get("id") == active_logo_id and item.get("status") == "available"
        ),
        None,
    )
    slide_logo = None
    if config.get("logo_mode", "none") != "none" and logo_candidate is not None:
        slide_logo = {
            **logo_candidate,
            "mode": config.get("logo_mode"),
            "placement": config.get("logo_placement", "top-right"),
            "size": config.get("logo_size", "small"),
            "margin_px": int(config.get("logo_margin_px", 32)),
            "opacity": float(config.get("logo_opacity", 1.0)),
            "visibility": config.get("logo_visibility")
            or {"cover": True, "content": True, "summary": True},
        }
    tts_config = None
    if profile.agent_type == "voice":
        candidate = dict(config)
        if not {"tts_provider", "tts_model", "tts_language", "tts_voice"}.issubset(
            candidate
        ):
            candidate.update(
                default_tts_config(
                    model=get_settings().tts_model,
                    voice=get_settings().tts_voice,
                )
            )
        try:
            tts_config = resolve_tts_config(candidate)
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"El perfil de voz «{profile.name}» usa una configuración TTS "
                    f"histórica no disponible: {exc}. Edita el perfil antes de ejecutar."
                ),
            ) from exc
    return {
        "soul_md": profile.soul_md,
        "agents_md": profile.agents_md,
        "model": config.get("model"),
        "orientation": config.get("orientation", "horizontal"),
        "images_enabled": bool(config.get("images_enabled", False)),
        "image_model": config.get("image_model") or DEFAULT_IMAGE_MODEL,
        "image_style": config.get("image_style") or DEFAULT_IMAGE_STYLE,
        "image_style_prompt": config.get("image_style_prompt") or "",
        "profile_id": profile.id,
        "profile_version": profile.active_version,
        "automatic_review_enabled": bool(config.get("automatic_review_enabled", False)),
        "max_automatic_regenerations": int(
            config.get("max_automatic_regenerations", 0) or 0
        ),
        "human_review_enabled": bool(config.get("human_review_enabled", False)),
        "evaluator_model": evaluator_model,
        "slide_palette": normalize_palette(config.get("slide_palette")),
        "slide_logo": slide_logo,
        "tts_config": tts_config,
        "subtitles_mode": (
            config.get("subtitles_mode", "none")
            if profile.agent_type == "video"
            else "none"
        ),
    }


def _base_payload(db: Session, project: Project) -> dict:
    # Reuse the idea brief when the project came from an ideation session.
    brief = None
    session = db.scalars(
        select(IdeationSession).where(IdeationSession.project_id == project.id).limit(1)
    ).first()
    if session is not None and session.brief_json:
        brief = json.loads(session.brief_json)
    project_dict = {
        "title": project.title,
        "topic": project.topic,
        "audience": project.audience,
        "level": project.level,
        "language": project.language,
        "style": project.style,
        "duration_spec": project.duration_spec,
        "research_mode": project.research_mode,
        "source_ids": (
            [source.id for source in project.sources if source.status == "ready"]
            if project.research_mode != "web_only"
            else []
        ),
    }
    return {
        "project_id": project.id,
        "project_title": project.title,
        "project": project_dict,
        "style": project.style,
        "duration_spec": project.duration_spec,
        "research_mode": project.research_mode,
        "source_ids": project_dict["source_ids"],
        "task_input": render_curator_input(project_dict, brief),
    }


@router.post(
    "/projects/{project_id}/agent-runs",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_run(project_id: str, body: AgentRunCreate, user: CurrentUser, db: DB):
    _begin_serialized_job_creation(db)
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    requested_kind = "pipeline_run" if body.agent == "pipeline" else f"{body.agent}_run"
    existing = _idempotent_project_job(
        db,
        project_id,
        body.request_id,
        kind=requested_kind,
    )
    if existing is not None:
        return _job_read(existing)
    _ensure_project_has_no_active_job(db, project_id)

    payload = _base_payload(db, project)

    selected_inputs = _selected_artifact_ids(db, project_id)
    available = set(selected_inputs)
    if body.expected_input_artifact_ids is not None:
        expected = {
            type_: sorted(set(ids))
            for type_, ids in body.expected_input_artifact_ids.items()
            if ids
        }
        current = {type_: sorted(ids) for type_, ids in selected_inputs.items() if ids}
        if expected != current:
            changed = sorted(
                type_
                for type_ in set(expected) | set(current)
                if expected.get(type_, []) != current.get(type_, [])
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    "La selección de artefactos cambió antes de iniciar la fase"
                    + (f": {', '.join(changed)}." if changed else ".")
                    + " Revisa las versiones activas y vuelve a confirmar."
                ),
            )

    if project.duration_spec is None and (
        body.agent == "pipeline"
        or body.agent in {"planner", "lessons", "slides", "script", "voice", "video", "publisher"}
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Configura la duración y estructura del proyecto antes de ejecutar "
                "planner o una fase posterior."
            ),
        )

    if body.agent == "pipeline":
        payload["stages"] = {
            agent: _profile_fields(get_default_profile(db, agent))
            for agent in RUNNABLE_AGENTS
        }
        kind = "pipeline_run"
    elif body.agent in RUNNABLE_AGENTS:
        missing = missing_agent_inputs(body.agent, available)
        if missing:
            raise HTTPException(
                status_code=409,
                detail="Faltan pasos previos: " + ", ".join(missing),
            )
        if body.profile_id:
            profile = db.get(AgentProfile, body.profile_id)
            if profile is None or profile.agent_type != body.agent:
                raise HTTPException(status_code=404, detail="Perfil no encontrado")
        else:
            profile = get_default_profile(db, body.agent)
        payload.update(_profile_fields(profile))
        payload["input_artifact_ids"] = selected_inputs
        payload["previous_output_artifact_ids"] = {
            type_: list(selected_inputs.get(type_, []))
            for type_ in AGENT_OUTPUTS[body.agent]
        }
        payload["request_id"] = body.request_id
        payload["trigger"] = body.trigger
        kind = f"{body.agent}_run"
    else:
        raise HTTPException(status_code=422, detail=f"Agente no ejecutable: {body.agent}")

    job = Job(kind=kind, project_id=project.id, payload_json=json.dumps(payload))
    db.add(job)
    db.commit()
    db.refresh(job)
    runner.enqueue(job.id)
    return _job_read(job)


@router.get("/projects/{project_id}/runs", response_model=list[JobRead])
def list_project_runs(project_id: str, user: CurrentUser, db: DB):
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    jobs = db.scalars(
        select(Job).where(Job.project_id == project_id).order_by(Job.created_at.desc())
    ).all()
    return [_job_read(j, include_events=False) for j in jobs]


@router.get("/runs/{job_id}", response_model=JobRead)
def get_run(job_id: str, user: CurrentUser, db: DB):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ejecución no encontrada")
    return _job_read(job)


@router.get("/runs/{job_id}/events")
async def stream_run_events(job_id: str, user: CurrentUser):
    """Server-Sent Events: replays stored events, then follows until done."""

    def _snapshot(after_seq: int):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return None, [], True
            events = [
                _event_read(e).model_dump(mode="json")
                for e in job.events
                if e.seq > after_seq
            ]
            finished = job.status in SSE_STOP_STATUSES
            return job.status, events, finished

    async def generator():
        last_seq = -1
        while True:
            status_, events, finished = await asyncio.to_thread(_snapshot, last_seq)
            if status_ is None:
                yield 'event: error\ndata: {"detail": "Ejecución no encontrada"}\n\n'
                return
            for event in events:
                last_seq = max(last_seq, event["seq"])
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if finished:
                payload = json.dumps({"status": status_}, ensure_ascii=False)
                yield f"event: done\ndata: {payload}\n\n"
                return
            yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
