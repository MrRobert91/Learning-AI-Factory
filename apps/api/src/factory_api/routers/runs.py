import asyncio
import json
from typing import Annotated

from factory_agents.agents.curator import render_curator_input
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.db import SessionLocal, get_db
from factory_api.models import AgentProfile, IdeationSession, Job, JobEvent, Project
from factory_api.routers.agents import get_default_profile
from factory_api.runner import runner
from factory_api.schemas import CuratorRunCreate, JobEventRead, JobRead

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
    return JobRead(
        id=job.id,
        kind=job.kind,
        status=job.status,
        error=job.error,
        project_id=job.project_id,
        result=json.loads(job.result_json) if job.result_json else None,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        events=[_event_read(e) for e in job.events] if include_events else [],
    )


@router.post(
    "/projects/{project_id}/curator-runs",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
)
def create_curator_run(project_id: str, body: CuratorRunCreate, user: CurrentUser, db: DB):
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")

    if body.profile_id:
        profile = db.get(AgentProfile, body.profile_id)
        if profile is None or profile.agent_type != "curator":
            raise HTTPException(status_code=404, detail="Perfil de curador no encontrado")
    else:
        profile = get_default_profile(db, "curator")

    # Reuse the idea brief when the project came from an ideation session.
    brief = None
    session = db.scalars(
        select(IdeationSession).where(IdeationSession.project_id == project_id).limit(1)
    ).first()
    if session is not None and session.brief_json:
        brief = json.loads(session.brief_json)

    config = json.loads(profile.config_json or "{}") if profile else {}
    payload = {
        "project_id": project.id,
        "project_title": project.title,
        "task_input": render_curator_input(
            {
                "title": project.title,
                "topic": project.topic,
                "audience": project.audience,
                "level": project.level,
                "language": project.language,
                "style": project.style,
            },
            brief,
        ),
        "soul_md": profile.soul_md if profile else "",
        "agents_md": profile.agents_md if profile else "",
        "model": config.get("model"),
    }
    job = Job(kind="curator_run", project_id=project.id, payload_json=json.dumps(payload))
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
            finished = job.status in ("done", "failed")
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
