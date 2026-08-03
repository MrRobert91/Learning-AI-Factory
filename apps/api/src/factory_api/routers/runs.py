import asyncio
import base64
import binascii
import json
from datetime import datetime
from typing import Annotated

from factory_agents.agents.curator import render_curator_input
from factory_agents.contracts.agent_io import AGENT_OUTPUTS
from factory_agents.tools.images import DEFAULT_IMAGE_MODEL, DEFAULT_IMAGE_STYLE
from factory_agents.tools.palette import DEFAULT_SLIDE_PALETTE, normalize_palette
from factory_agents.tools.tts import default_tts_config
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.config import get_settings
from factory_api.db import SessionLocal, get_db
from factory_api.events import event_broker, event_repository
from factory_api.job_access import get_owned_job
from factory_api.models import AgentProfile, Artifact, IdeationSession, Job, JobEvent, Project
from factory_api.routers.agents import get_default_profile
from factory_api.run_control import SSE_STOP_STATUSES, load_control
from factory_api.runner import runner
from factory_api.schemas import (
    AgentRunCreate,
    JobEventPage,
    JobEventRead,
    JobPage,
    JobRead,
    JobSummary,
)
from factory_api.tts_catalog import resolve_current_tts_config
from factory_api.usage import job_usage_summaries, job_usage_summary
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


def _review_policies(job: Job, payload: dict) -> dict[str, dict]:
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
    return review_policies


def _job_read(job: Job, include_events: bool = True) -> JobRead:
    payload = json.loads(job.payload_json or "{}")
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
        review_policies=_review_policies(job, payload),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        events=[_event_read(e) for e in job.events] if include_events else [],
    )


def _job_summary_read(job: Job, usage_summary: dict) -> JobSummary:
    payload = json.loads(job.payload_json or "{}")
    return JobSummary(
        id=job.id,
        kind=job.kind,
        status=job.status,
        error=job.error,
        project_id=job.project_id,
        workflow_id=payload.get("workflow_id"),
        workflow_name=payload.get("workflow_name"),
        control=load_control(job),
        usage_summary=usage_summary,
        review_policies=_review_policies(job, payload),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
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
        background_mode = config.get("logo_background_mode", "opaque")
        transparent_variant = logo_candidate.get("transparent_variant") or {}
        effective = (
            transparent_variant
            if background_mode == "transparent"
            else logo_candidate
        )
        slide_logo = {
            **logo_candidate,
            "mode": config.get("logo_mode"),
            "background_mode": background_mode,
            "original_path": logo_candidate.get("path"),
            "original_media_type": logo_candidate.get("media_type"),
            "original_width": logo_candidate.get("width"),
            "original_height": logo_candidate.get("height"),
            "original_sha256": logo_candidate.get("sha256"),
            "effective_path": effective.get("path"),
            "effective_media_type": effective.get("media_type"),
            "effective_width": effective.get("width"),
            "effective_height": effective.get("height"),
            "effective_sha256": effective.get("sha256"),
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
            tts_config = resolve_current_tts_config(candidate)
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


def _encode_run_cursor(job: Job) -> str:
    raw = json.dumps([job.created_at.isoformat(), job.id], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_run_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created_at, job_id = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(created_at, str) or not isinstance(job_id, str) or not job_id:
            raise ValueError
        return datetime.fromisoformat(created_at), job_id
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Cursor de ejecuciones no válido") from exc


@router.get("/projects/{project_id}/runs", response_model=JobPage)
def list_project_runs(
    project_id: str,
    user: CurrentUser,
    db: DB,
    cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
):
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    stmt = select(Job).where(Job.project_id == project_id)
    if cursor:
        cursor_created_at, cursor_id = _decode_run_cursor(cursor)
        stmt = stmt.where(
            or_(
                Job.created_at < cursor_created_at,
                and_(Job.created_at == cursor_created_at, Job.id < cursor_id),
            )
        )
    jobs = list(
        db.scalars(
            stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit + 1)
        ).all()
    )
    has_more = len(jobs) > limit
    page_jobs = jobs[:limit]
    active_job = db.scalars(
        select(Job)
        .where(
            Job.project_id == project_id,
            Job.status.in_(ACTIVE_PROJECT_JOB_STATUSES),
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    ).first()
    summary_jobs = list(page_jobs)
    if active_job is not None and all(job.id != active_job.id for job in summary_jobs):
        summary_jobs.append(active_job)
    usage = job_usage_summaries(db, [job.id for job in summary_jobs])
    empty_usage = {"has_data": False, "records": 0}
    items = [
        _job_summary_read(job, usage.get(job.id, empty_usage)) for job in page_jobs
    ]
    active = (
        _job_summary_read(active_job, usage.get(active_job.id, empty_usage))
        if active_job is not None
        else None
    )
    return JobPage(
        items=items,
        active=active,
        next_cursor=_encode_run_cursor(page_jobs[-1]) if has_more and page_jobs else None,
    )


@router.get("/runs/{job_id}", response_model=JobRead)
def get_run(job_id: str, user: CurrentUser, db: DB):
    job = get_owned_job(db, user.id, job_id)
    return _job_read(job)


@router.get("/runs/{job_id}/event-history", response_model=JobEventPage)
def get_run_event_history(
    job_id: str,
    user: CurrentUser,
    db: DB,
    after_seq: int = Query(default=-1, ge=-1),
    limit: int = Query(default=200, ge=1, le=1000),
):
    get_owned_job(db, user.id, job_id)
    events = event_repository.page(
        db, job_id, after_seq=after_seq, limit=limit + 1
    )
    has_more = len(events) > limit
    page = events[:limit]
    return JobEventPage(
        items=[_event_read(event) for event in page],
        next_after_seq=page[-1].seq if has_more and page else None,
    )


@router.get("/runs/{job_id}/events")
async def stream_run_events(
    request: Request,
    job_id: str,
    user: CurrentUser,
    db: DB,
    after_seq: str | None = None,
):
    """Replay after Last-Event-ID (preferred) or after_seq, then follow commits."""

    get_owned_job(db, user.id, job_id)
    db.close()
    raw_cursor = request.headers.get("last-event-id")
    if raw_cursor in (None, ""):
        raw_cursor = after_seq
    try:
        initial_seq = int(raw_cursor) if raw_cursor not in (None, "") else -1
        if initial_seq < -1:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Cursor SSE no válido") from exc

    settings = get_settings()
    batch_size = settings.job_event_batch_size
    keepalive_seconds = settings.job_event_keepalive_seconds

    def _snapshot(after_seq: int):
        with SessionLocal() as snapshot_db:
            events = event_repository.page(
                snapshot_db,
                job_id,
                after_seq=after_seq,
                limit=batch_size,
            )
            status_ = (
                snapshot_db.scalar(select(Job.status).where(Job.id == job_id))
                if len(events) < batch_size
                else None
            )
            return status_, events

    async def generator():
        last_seq = initial_seq
        async with event_broker.subscribe(job_id) as signal:
            while True:
                signal.clear()
                status_, stored_events = await asyncio.to_thread(_snapshot, last_seq)
                if status_ is None and len(stored_events) < batch_size:
                    yield 'event: error\ndata: {"detail": "Ejecución no encontrada"}\n\n'
                    return
                for stored_event in stored_events:
                    event = _event_read(stored_event).model_dump(mode="json")
                    last_seq = stored_event.seq
                    yield (
                        f"id: {stored_event.seq}\n"
                        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    )
                if len(stored_events) == batch_size:
                    continue
                if status_ in SSE_STOP_STATUSES:
                    payload = json.dumps({"status": status_}, ensure_ascii=False)
                    id_line = f"id: {last_seq}\n" if last_seq >= 0 else ""
                    yield f"{id_line}event: done\ndata: {payload}\n\n"
                    return
                while not signal.is_set():
                    try:
                        await asyncio.wait_for(signal.wait(), timeout=keepalive_seconds)
                    except TimeoutError:
                        yield ": keepalive\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
