import json
from typing import Annotated

from factory_agents.agents.ideation import AgentEvent, HistoryItem, run_ideation_turn
from factory_agents.llm import MissingApiKeyError, get_llm_client
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.config import get_settings
from factory_api.db import get_db
from factory_api.models import IdeationMessage, IdeationSession, Project
from factory_api.schemas import (
    IdeationCreate,
    IdeationMessageCreate,
    IdeationMessageRead,
    IdeationSessionRead,
    IdeationSessionSummary,
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


def _session_read(session: IdeationSession) -> IdeationSessionRead:
    return IdeationSessionRead(
        id=session.id,
        status=session.status,
        initial_idea=session.initial_idea,
        project_id=session.project_id,
        has_brief=session.brief_json is not None,
        brief=json.loads(session.brief_json) if session.brief_json else None,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[_message_read(m) for m in session.messages],
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


def _run_agent(db: Session, session: IdeationSession) -> list[AgentEvent]:
    from factory_api.routers.agents import get_default_profile

    settings = get_settings()
    profile = get_default_profile(db, "ideation")
    try:
        client = get_llm_client(settings.openrouter_api_key)
        events = run_ideation_turn(
            client,
            session.model,
            _history(session),
            soul_md=profile.soul_md if profile else "",
            agents_md=profile.agents_md if profile else "",
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
        _append(db, session, "assistant", event.kind, event.content, event.payload or None)
        if event.kind == "brief":
            session.brief_json = json.dumps(event.payload, ensure_ascii=False)
    db.commit()
    db.refresh(session)
    return events


@router.post("", response_model=IdeationSessionRead, status_code=status.HTTP_201_CREATED)
def create_session(body: IdeationCreate, user: CurrentUser, db: DB):
    settings = get_settings()
    session = IdeationSession(
        owner_id=user.id,
        initial_idea=body.idea,
        model=settings.openrouter_model,
    )
    db.add(session)
    db.flush()
    _append(db, session, "user", "text", body.idea)
    db.commit()
    db.refresh(session)
    _run_agent(db, session)
    return _session_read(session)


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
            has_brief=s.brief_json is not None,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in db.scalars(stmt).all()
    ]


@router.get("/{session_id}", response_model=IdeationSessionRead)
def get_session(session_id: str, user: CurrentUser, db: DB):
    return _session_read(_get_owned_session(db, user.id, session_id))


@router.post("/{session_id}/messages", response_model=IdeationSessionRead)
def send_message(session_id: str, body: IdeationMessageCreate, user: CurrentUser, db: DB):
    session = _get_owned_session(db, user.id, session_id)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="La sesión ya está finalizada")
    last = session.messages[-1] if session.messages else None
    kind = "answer" if last is not None and last.kind == "question" else "text"
    _append(db, session, "user", kind, body.content)
    db.commit()
    db.refresh(session)
    _run_agent(db, session)
    return _session_read(session)


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
    brief = json.loads(session.brief_json)
    project = Project(
        owner_id=user.id,
        title=brief.get("working_title") or session.initial_idea[:255],
        topic=brief.get("topic", ""),
        audience=brief.get("audience", ""),
        level=brief.get("level", ""),
        language=brief.get("language", "es"),
        style=brief.get("style", ""),
        output_format=brief.get("output_format", ""),
    )
    db.add(project)
    db.flush()
    session.status = "finalized"
    session.project_id = project.id
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: str, user: CurrentUser, db: DB):
    session = _get_owned_session(db, user.id, session_id)
    db.delete(session)
    db.commit()
