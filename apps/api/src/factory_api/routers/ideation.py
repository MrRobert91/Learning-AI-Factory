import asyncio
import hashlib
import json
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from factory_agents.agents.ideation import AgentEvent, HistoryItem, run_ideation_turn
from factory_agents.contracts import CourseIdeaBrief
from factory_agents.duration import research_budget
from factory_agents.llm import MissingApiKeyError, get_llm_client
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.config import get_settings
from factory_api.db import SessionLocal, get_db
from factory_api.ideation_sources import (
    MAX_SOURCE_BYTES,
    MAX_SOURCES,
    SourceIngestionError,
    capture_bytes,
    capture_url,
    store_captured_source,
)
from factory_api.models import IdeationMessage, IdeationSession, IdeationSource, Project
from factory_api.schemas import (
    IdeationCreate,
    IdeationDraftCreate,
    IdeationMessageCreate,
    IdeationMessageRead,
    IdeationResearchModeUpdate,
    IdeationSessionRead,
    IdeationSessionSummary,
    IdeationSourceRead,
    IdeationUrlCreate,
    ProjectRead,
)

router = APIRouter(prefix="/api/ideation", tags=["ideation"])

DB = Annotated[Session, Depends(get_db)]


def _get_owned_session(db: Session, user_id: str, session_id: str) -> IdeationSession:
    session = db.get(IdeationSession, session_id)
    if session is None or session.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return session


def _message_read(msg: IdeationMessage) -> IdeationMessageRead:
    return IdeationMessageRead(
        id=msg.id,
        seq=msg.seq,
        role=msg.role,
        kind=msg.kind,
        content=msg.content,
        payload=json.loads(msg.payload_json) if msg.payload_json else None,
        created_at=msg.created_at,
    )


def _source_read(source: IdeationSource) -> IdeationSourceRead:
    return IdeationSourceRead(
        id=source.id,
        session_id=source.session_id,
        project_id=source.project_id,
        kind=source.kind,
        media_type=source.media_type,
        name=source.name,
        original_url=source.original_url,
        final_url=source.final_url,
        sha256=source.sha256,
        size_bytes=source.size_bytes,
        status=source.status,
        error=source.error,
        metadata=source.source_metadata,
        captured_at=source.captured_at,
    )


def _source_document(source: IdeationSource) -> dict:
    return {
        "id": source.id,
        "name": source.name,
        "kind": source.kind,
        "media_type": source.media_type,
        "size_bytes": source.size_bytes,
        "text": source.extracted_text,
        "metadata": source.source_metadata,
    }


def _session_read(session: IdeationSession) -> IdeationSessionRead:
    return IdeationSessionRead(
        id=session.id,
        status=session.status,
        initial_idea=session.initial_idea,
        project_id=session.project_id,
        research_mode=session.research_mode,
        source_count=len(session.sources),
        has_brief=session.brief_json is not None,
        brief=json.loads(session.brief_json) if session.brief_json else None,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[_message_read(m) for m in session.messages],
        sources=[_source_read(source) for source in session.sources],
    )


def _history(session: IdeationSession) -> list[HistoryItem]:
    return [
        HistoryItem(
            role=m.role,  # type: ignore[arg-type]
            kind=m.kind,
            content=m.content,
            payload=json.loads(m.payload_json) if m.payload_json else {},
        )
        for m in session.messages
        if m.kind != "progress"
    ]


def _append(db: Session, session: IdeationSession, role: str, kind: str, content: str,
            payload: dict | None = None) -> IdeationMessage:
    seq = len(session.messages)
    msg = IdeationMessage(
        session_id=session.id,
        seq=seq,
        role=role,
        kind=kind,
        content=content,
        payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
    )
    db.add(msg)
    session.messages.append(msg)
    return msg


def _create_session_record(
    db: Session,
    user_id: str,
    body: IdeationCreate,
) -> IdeationSession:
    settings = get_settings()
    session = IdeationSession(
        owner_id=user_id,
        initial_idea=body.idea,
        model=settings.openrouter_model,
        research_mode=body.research_mode,
    )
    db.add(session)
    db.flush()
    _append(db, session, "user", "text", body.idea)
    db.commit()
    db.refresh(session)
    return session


def _ensure_source_slot(session: IdeationSession) -> None:
    if session.status != "active":
        raise HTTPException(status_code=409, detail="La sesión ya está finalizada")
    if len(session.sources) >= MAX_SOURCES:
        raise HTTPException(status_code=409, detail="La sesión admite como máximo 10 fuentes")


def _persist_capture(
    db: Session,
    session: IdeationSession,
    capture,
    *,
    fallback_name: str,
    fallback_bytes: bytes,
    error: str = "",
) -> IdeationSource:
    source_id = uuid.uuid4().hex
    path = ""
    if capture is not None:
        path = store_captured_source(
            capture,
            data_dir=get_settings().data_dir,
            session_id=session.id,
            source_id=source_id,
        )
    source = IdeationSource(
        id=source_id,
        session_id=session.id,
        kind=capture.kind if capture is not None else "unknown",
        media_type=capture.media_type if capture is not None else "application/octet-stream",
        name=capture.name if capture is not None else Path(fallback_name).name[:255],
        original_url=capture.original_url if capture is not None else None,
        final_url=capture.final_url if capture is not None else None,
        path=path,
        extracted_text=capture.extracted_text if capture is not None else "",
        sha256=(
            capture.sha256
            if capture is not None
            else hashlib.sha256(fallback_bytes).hexdigest()
        ),
        size_bytes=len(capture.content) if capture is not None else len(fallback_bytes),
        status="ready" if capture is not None else "failed",
        error=error,
        metadata_json=(
            json.dumps(capture.metadata, ensure_ascii=False)
            if capture is not None
            else "{}"
        ),
    )
    db.add(source)
    session.brief_json = None
    db.commit()
    db.refresh(source)
    db.refresh(session)
    return source


def _run_agent(
    db: Session,
    session: IdeationSession,
    on_progress: Callable[[IdeationMessageRead], None] | None = None,
) -> list[AgentEvent]:
    from factory_api.routers.agents import get_default_profile

    settings = get_settings()
    profile = get_default_profile(db, "ideation")
    ready_sources = [source for source in session.sources if source.status == "ready"]
    effective_sources = (
        ready_sources if session.research_mode != "web_only" else []
    )
    max_source_queries = 12
    if session.brief_json:
        try:
            brief = CourseIdeaBrief.model_validate_json(session.brief_json)
            max_source_queries = research_budget(
                brief.duration_spec.total_minutes
            )["searches_max"]
        except Exception:
            pass
    try:
        client = get_llm_client(settings.openrouter_api_key)

        def record_progress(kind: str, summary: str, data: dict) -> None:
            message = _append(
                db,
                session,
                "assistant",
                "progress",
                summary,
                {"phase": kind, **data},
            )
            db.commit()
            db.refresh(message)
            if on_progress:
                on_progress(_message_read(message))

        events = run_ideation_turn(
            client,
            session.model,
            _history(session),
            soul_md=profile.soul_md if profile else "",
            agents_md=profile.agents_md if profile else "",
            on_progress=record_progress,
            research_mode=session.research_mode,
            source_documents=[_source_document(source) for source in effective_sources],
            max_source_queries=max_source_queries,
        )
    except MissingApiKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Falta OPENROUTER_API_KEY: configúrala en el .env para usar los agentes",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error del proveedor LLM: {exc}",
        ) from exc

    for event in events:
        if event.kind == "brief":
            event.payload["research_mode"] = session.research_mode
            event.payload["source_ids"] = [source.id for source in effective_sources]
        _append(db, session, "assistant", event.kind, event.content, event.payload or None)
        if event.kind == "brief":
            session.brief_json = json.dumps(event.payload, ensure_ascii=False)
    db.commit()
    db.refresh(session)
    return events


def _stream_agent_response(session_id: str, user_id: str) -> StreamingResponse:
    async def generator():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

        def emit(message: IdeationMessageRead) -> None:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                ("progress", message.model_dump(mode="json")),
            )

        def work() -> None:
            try:
                with SessionLocal() as worker_db:
                    session = _get_owned_session(worker_db, user_id, session_id)
                    _run_agent(worker_db, session, on_progress=emit)
                    worker_db.refresh(session)
                    payload = _session_read(session).model_dump(mode="json")
                loop.call_soon_threadsafe(queue.put_nowait, ("result", payload))
            except Exception as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    ("error", {"detail": detail or "Error del agente de ideación"}),
                )

        worker = asyncio.create_task(asyncio.to_thread(work))
        try:
            while True:
                event, payload = await queue.get()
                yield (
                    f"event: {event}\n"
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                )
                if event in {"result", "error"}:
                    break
        finally:
            await worker

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("", response_model=IdeationSessionRead, status_code=status.HTTP_201_CREATED)
def create_session(body: IdeationCreate, user: CurrentUser, db: DB):
    session = _create_session_record(db, user.id, body)
    _run_agent(db, session)
    return _session_read(session)


@router.post("/stream")
def create_session_stream(body: IdeationCreate, user: CurrentUser, db: DB):
    session = _create_session_record(db, user.id, body)
    return _stream_agent_response(session.id, user.id)


@router.post(
    "/draft",
    response_model=IdeationSessionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_session_draft(body: IdeationDraftCreate, user: CurrentUser, db: DB):
    return _session_read(_create_session_record(db, user.id, body))


@router.post("/{session_id}/start/stream")
def start_session_stream(session_id: str, user: CurrentUser, db: DB):
    session = _get_owned_session(db, user.id, session_id)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="La sesión ya está finalizada")
    if any(message.role == "assistant" for message in session.messages):
        raise HTTPException(status_code=409, detail="La sesión de ideación ya ha comenzado")
    return _stream_agent_response(session.id, user.id)


@router.get("", response_model=list[IdeationSessionSummary])
def list_sessions(user: CurrentUser, db: DB):
    stmt = (
        select(IdeationSession)
        .where(IdeationSession.owner_id == user.id)
        .order_by(IdeationSession.updated_at.desc())
    )
    return [
        IdeationSessionSummary(
            id=s.id,
            status=s.status,
            initial_idea=s.initial_idea,
            project_id=s.project_id,
            research_mode=s.research_mode,
            source_count=len(s.sources),
            has_brief=s.brief_json is not None,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in db.scalars(stmt).all()
    ]


@router.get("/{session_id}", response_model=IdeationSessionRead)
def get_session(session_id: str, user: CurrentUser, db: DB):
    return _session_read(_get_owned_session(db, user.id, session_id))


@router.patch("/{session_id}", response_model=IdeationSessionRead)
def update_session(
    session_id: str,
    body: IdeationResearchModeUpdate,
    user: CurrentUser,
    db: DB,
):
    session = _get_owned_session(db, user.id, session_id)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="La sesión ya está finalizada")
    if session.research_mode != body.research_mode:
        session.research_mode = body.research_mode
        session.brief_json = None
        _append(
            db,
            session,
            "assistant",
            "progress",
            "Política de investigación actualizada; el próximo brief usará esta configuración.",
            {"phase": "stage", "research_mode": body.research_mode},
        )
        db.commit()
        db.refresh(session)
    return _session_read(session)


@router.post(
    "/{session_id}/sources/file",
    response_model=IdeationSourceRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_source_file(
    session_id: str,
    user: CurrentUser,
    db: DB,
    file: Annotated[UploadFile, File()],
):
    session = _get_owned_session(db, user.id, session_id)
    _ensure_source_slot(session)
    content = await file.read(MAX_SOURCE_BYTES + 1)
    try:
        captured = capture_bytes(
            content,
            filename=file.filename or "fuente",
            content_type=file.content_type or "",
        )
        if captured.kind == "html":
            raise SourceIngestionError(
                "Los ficheros HTML no se admiten; añade la página mediante su URL pública"
            )
    except SourceIngestionError as exc:
        source = _persist_capture(
            db,
            session,
            None,
            fallback_name=file.filename or "fuente",
            fallback_bytes=content,
            error=str(exc),
        )
        return _source_read(source)
    return _source_read(
        _persist_capture(
            db,
            session,
            captured,
            fallback_name=file.filename or "fuente",
            fallback_bytes=content,
        )
    )


@router.post(
    "/{session_id}/sources/url",
    response_model=IdeationSourceRead,
    status_code=status.HTTP_201_CREATED,
)
def add_source_url(
    session_id: str,
    body: IdeationUrlCreate,
    user: CurrentUser,
    db: DB,
):
    session = _get_owned_session(db, user.id, session_id)
    _ensure_source_slot(session)
    raw_url = body.url.strip()
    try:
        captured = capture_url(raw_url)
    except SourceIngestionError as exc:
        source = _persist_capture(
            db,
            session,
            None,
            fallback_name=raw_url,
            fallback_bytes=raw_url.encode(),
            error=str(exc),
        )
        source.original_url = raw_url
        db.commit()
        db.refresh(source)
        return _source_read(source)
    return _source_read(
        _persist_capture(
            db,
            session,
            captured,
            fallback_name=raw_url,
            fallback_bytes=captured.content,
        )
    )


@router.delete("/{session_id}/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    session_id: str,
    source_id: str,
    user: CurrentUser,
    db: DB,
):
    session = _get_owned_session(db, user.id, session_id)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="La sesión ya está finalizada")
    source = db.get(IdeationSource, source_id)
    if source is None or source.session_id != session.id:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    if source.path:
        root = get_settings().data_dir.resolve()
        path = (get_settings().data_dir / source.path).resolve()
        if path.is_relative_to(root):
            shutil.rmtree(path.parent, ignore_errors=True)
    db.delete(source)
    session.brief_json = None
    db.commit()


def _get_owned_source(
    db: Session,
    user_id: str,
    source_id: str,
) -> IdeationSource:
    source = db.get(IdeationSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    session_owned = (
        source.session is not None and source.session.owner_id == user_id
    )
    project_owned = (
        source.project is not None and source.project.owner_id == user_id
    )
    if not session_owned and not project_owned:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    return source


@router.get("/sources/{source_id}/original")
def download_source(source_id: str, user: CurrentUser, db: DB):
    source = _get_owned_source(db, user.id, source_id)
    path = get_settings().data_dir / source.path
    if source.status != "ready" or not source.path or not path.is_file():
        raise HTTPException(status_code=404, detail="Original no disponible")
    return FileResponse(path, media_type=source.media_type, filename=source.name)


@router.get("/sources/{source_id}/text", response_class=PlainTextResponse)
def read_source_text(source_id: str, user: CurrentUser, db: DB):
    source = _get_owned_source(db, user.id, source_id)
    if source.status != "ready":
        raise HTTPException(status_code=409, detail="La extracción no está disponible")
    return PlainTextResponse(source.extracted_text, media_type="text/plain; charset=utf-8")


@router.post("/{session_id}/messages", response_model=IdeationSessionRead)
def send_message(session_id: str, body: IdeationMessageCreate, user: CurrentUser, db: DB):
    session = _get_owned_session(db, user.id, session_id)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="La sesión ya está finalizada")
    last = next(
        (message for message in reversed(session.messages) if message.kind != "progress"),
        None,
    )
    kind = "answer" if last is not None and last.kind == "question" else "text"
    _append(db, session, "user", kind, body.content)
    db.commit()
    db.refresh(session)
    _run_agent(db, session)
    return _session_read(session)


@router.post("/{session_id}/messages/stream")
def send_message_stream(
    session_id: str, body: IdeationMessageCreate, user: CurrentUser, db: DB
):
    session = _get_owned_session(db, user.id, session_id)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="La sesión ya está finalizada")
    last = next(
        (message for message in reversed(session.messages) if message.kind != "progress"),
        None,
    )
    kind = "answer" if last is not None and last.kind == "question" else "text"
    _append(db, session, "user", kind, body.content)
    db.commit()
    return _stream_agent_response(session.id, user.id)


@router.post("/{session_id}/finalize", response_model=ProjectRead)
def finalize_session(session_id: str, user: CurrentUser, db: DB):
    session = _get_owned_session(db, user.id, session_id)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="La sesión ya está finalizada")
    if not session.brief_json:
        raise HTTPException(
            status_code=409,
            detail="Todavía no hay un brief propuesto: sigue la conversación hasta tenerlo",
        )
    try:
        brief = CourseIdeaBrief.model_validate_json(session.brief_json)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "El brief no incluye una duración válida. Pide al asistente que elija "
                "un preset o una estructura personalizada antes de crear el proyecto."
            ),
        ) from exc
    project = Project(
        owner_id=user.id,
        title=brief.working_title or session.initial_idea[:255],
        topic=brief.topic,
        audience=brief.audience,
        level=brief.level,
        language=brief.language,
        style=brief.style,
        output_format=brief.output_format,
        duration_spec_json=brief.duration_spec.model_dump_json(),
        research_mode=session.research_mode,
    )
    db.add(project)
    db.flush()
    ready_sources = [source for source in session.sources if source.status == "ready"]
    if session.research_mode == "provided_only" and not ready_sources:
        raise HTTPException(
            status_code=409,
            detail="El modo «Solo fuentes proporcionadas» requiere al menos una fuente válida",
        )
    for source in ready_sources:
        source.project_id = project.id
    session.status = "finalized"
    session.project_id = project.id
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, user: CurrentUser, db: DB):
    session = _get_owned_session(db, user.id, session_id)
    for source in list(session.sources):
        if source.project_id is not None:
            source.session_id = None
            continue
        if source.path:
            path = get_settings().data_dir / source.path
            shutil.rmtree(path.parent, ignore_errors=True)
        db.delete(source)
    db.delete(session)
    db.commit()
