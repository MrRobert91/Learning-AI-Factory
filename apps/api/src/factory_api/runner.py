"""In-process task runner.

Jobs are persisted in SQLite (they survive restarts: queued jobs are
re-enqueued on boot) and executed one at a time by an asyncio worker.
Agent work runs in a thread (deep agents are sync) and reports progress
by appending JobEvents, which the SSE endpoint streams to the UI.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from factory_api.config import get_settings
from factory_api.db import SessionLocal
from factory_api.models import Artifact, Job, JobEvent

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self) -> None:
        # The queue is created in start() so it binds to the running loop
        # (the app can be started several times in one process, e.g. tests).
        self._queue: asyncio.Queue[str] | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._queue = asyncio.Queue()
        with SessionLocal() as db:
            pending = db.scalars(
                select(Job.id).where(Job.status.in_(["queued", "running"]))
            ).all()
        for job_id in pending:
            self._queue.put_nowait(job_id)
        self._task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        self._queue = None

    def enqueue(self, job_id: str) -> None:
        # If the runner is not started the job stays queued in the DB and is
        # picked up on the next start().
        if self._queue is not None:
            self._queue.put_nowait(job_id)

    async def _worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await asyncio.to_thread(self._execute, job_id)
            except Exception:
                logger.exception("Job %s crashed outside handler", job_id)

    def _execute(self, job_id: str) -> None:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None or job.status in ("done", "failed"):
                return
            job.status = "running"
            job.started_at = datetime.now(UTC)
            db.commit()
            kind, payload = job.kind, json.loads(job.payload_json)

        try:
            handler = HANDLERS[kind]
        except KeyError:
            self._finish(job_id, error=f"Tipo de job desconocido: {kind}")
            return
        try:
            result = handler(job_id, payload)
            self._finish(job_id, result=result)
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            self._finish(job_id, error=str(exc))

    def _finish(self, job_id: str, result: dict | None = None, error: str = "") -> None:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            job.status = "failed" if error else "done"
            job.error = error
            job.result_json = json.dumps(result, ensure_ascii=False) if result else None
            job.finished_at = datetime.now(UTC)
            db.commit()


def append_event(job_id: str, type_: str, summary: str, data: dict | None = None) -> None:
    with SessionLocal() as db:
        seq = db.scalars(
            select(JobEvent.seq).where(JobEvent.job_id == job_id).order_by(JobEvent.seq.desc())
        ).first()
        db.add(
            JobEvent(
                job_id=job_id,
                seq=(seq + 1) if seq is not None else 0,
                type=type_,
                summary=summary,
                data_json=json.dumps(data, ensure_ascii=False) if data else None,
            )
        )
        db.commit()


def _save_artifact(
    job_id: str, project_id: str, type_: str, title: str, content: str, format_: str = "markdown"
) -> str:
    settings = get_settings()
    ext = {"markdown": "md", "json": "json"}.get(format_, "txt")
    rel_path = f"artifacts/{project_id}/{type_}-{job_id}.{ext}"
    abs_path = settings.data_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    with SessionLocal() as db:
        artifact = Artifact(
            project_id=project_id,
            type=type_,
            format=format_,
            title=title,
            path=rel_path,
            created_by_job_id=job_id,
        )
        db.add(artifact)
        db.commit()
        return artifact.id


def run_curator_job(job_id: str, payload: dict) -> dict:
    # Imported lazily so tests can monkeypatch factory_agents pieces easily.
    from factory_agents.agents.curator import run_curator

    settings = get_settings()
    workspace = settings.data_dir / "runs" / job_id
    final_text = ""
    for event in run_curator(
        payload["task_input"],
        model=payload.get("model") or settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        tavily_api_key=settings.tavily_api_key,
        workspace_dir=str(workspace),
        soul_md=payload.get("soul_md", ""),
        agents_md=payload.get("agents_md", ""),
    ):
        if event.type == "result":
            final_text = event.summary
        else:
            append_event(job_id, event.type, event.summary, event.data)

    if not final_text.strip():
        raise RuntimeError("El curador terminó sin producir un brief")

    artifact_id = _save_artifact(
        job_id,
        payload["project_id"],
        "research_brief",
        f"Research brief — {payload.get('project_title', '')}".strip(" —"),
        final_text,
    )
    append_event(job_id, "artifact", "Research brief generado", {"artifact_id": artifact_id})
    return {"artifact_id": artifact_id}


HANDLERS = {
    "curator_run": run_curator_job,
}

runner = JobRunner()
