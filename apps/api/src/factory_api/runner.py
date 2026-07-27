"""In-process task runner.

Jobs are persisted in SQLite (they survive restarts: queued jobs are
re-enqueued on boot) and executed one at a time by an asyncio worker.
Agent work runs in a thread (deep agents are sync) and reports progress
by appending JobEvents, which the SSE endpoint streams to the UI.
"""

import asyncio
import json
import logging
import shutil
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from factory_agents.contracts import DurationSpec
from factory_agents.duration import (
    duration_metrics,
    render_duration_constraints,
    research_budget,
    validate_course_plan_structure,
)
from sqlalchemy import func, select, update

from factory_api.artifact_versions import (
    add_artifact_version,
    artifact_logical_key,
    artifact_metadata,
    selected_artifact,
)
from factory_api.config import get_settings
from factory_api.db import SessionLocal
from factory_api.models import Artifact, Job, JobEvent, UsageRecord
from factory_api.run_control import (
    RunCanceled,
    RunPaused,
    checkpoint,
    completed_unit,
    load_scope_state,
    recover_jobs,
    save_scope_state,
)
from factory_api.usage import (
    attach_usage_to_artifact,
    record_usage,
    usage_record_by_work_unit,
)

logger = logging.getLogger(__name__)
_CURRENT_WORKFLOW_STEP: ContextVar[int | None] = ContextVar(
    "current_workflow_step", default=None
)


class JobRunner:
    def __init__(self) -> None:
        # The queue is created in start() so it binds to the running loop
        # (the app can be started several times in one process, e.g. tests).
        self._queue: asyncio.Queue[str] | None = None
        self._task: asyncio.Task | None = None
        self._queued_ids: set[str] = set()

    async def start(self) -> None:
        self._queue = asyncio.Queue()
        with SessionLocal() as db:
            pending, recovery_events = recover_jobs(db)
        for job_id in pending:
            self._queued_ids.add(job_id)
            self._queue.put_nowait(job_id)
        for job_id, summary, point in recovery_events:
            append_event(
                job_id,
                "control",
                summary,
                {
                    "status": (
                        "paused"
                        if "Pausa" in summary
                        else "canceled"
                        if "Cancelación" in summary
                        else "queued"
                    ),
                    "checkpoint": point,
                },
            )
        self._task = asyncio.create_task(self._worker())
        logger.info(
            "Job runner started",
            extra={"recovered_jobs": len(pending)},
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        self._queue = None
        self._queued_ids.clear()
        logger.info("Job runner stopped")

    def enqueue(self, job_id: str) -> None:
        # If the runner is not started the job stays queued in the DB and is
        # picked up on the next start().
        if self._queue is not None and job_id not in self._queued_ids:
            self._queued_ids.add(job_id)
            self._queue.put_nowait(job_id)
            logger.info("Job enqueued", extra={"job_id": job_id})

    async def _worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            self._queued_ids.discard(job_id)
            try:
                await asyncio.to_thread(self._execute, job_id)
            except Exception:
                logger.exception("Job %s crashed outside handler", job_id)
            finally:
                self._queue.task_done()

    def _execute(self, job_id: str) -> None:
        with SessionLocal() as db:
            claimed = db.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "queued")
                .values(status="running", finished_at=None, error="")
            )
            if claimed.rowcount != 1:
                db.rollback()
                return
            db.commit()
            job = db.get(Job, job_id)
            if job is None:
                return
            job.started_at = job.started_at or datetime.now(UTC)
            db.commit()
            kind, payload = job.kind, json.loads(job.payload_json)
            logger.info(
                "Job execution started",
                extra={
                    "job_id": job_id,
                    "job_kind": kind,
                    "project_id": job.project_id,
                },
            )
        with SessionLocal() as db:
            persisted_tokens = db.scalar(
                select(func.coalesce(func.sum(UsageRecord.total_tokens), 0)).where(
                    UsageRecord.job_id == job_id
                )
            )
        _TOKENS_USED[job_id] = int(persisted_tokens or 0)

        try:
            handler = HANDLERS[kind]
        except KeyError:
            self._finish(job_id, error=f"Tipo de job desconocido: {kind}")
            return
        try:
            direct_agent = (
                kind.removesuffix("_run")
                if kind
                in {
                    f"{agent}_run"
                    for agent in (
                        "curator",
                        "planner",
                        "lessons",
                        "slides",
                        "script",
                        "voice",
                        "video",
                        "publisher",
                    )
                }
                else None
            )
            resume = payload.get("_resume") or {}
            if direct_agent is not None and resume.get("approved") is True:
                result = dict(payload.get("_pending_result") or {})
                result["human_review"] = {
                    "agent": direct_agent,
                    "feedback_cycles": list(
                        payload.get("_human_feedback_history", [])
                    ),
                    "final_decision": "approved",
                }
            elif direct_agent is not None:
                effective_payload = dict(payload)
                if resume.get("approved") is False:
                    effective_payload["revision_feedback"] = resume.get("feedback", "")
                history = list(payload.get("_human_feedback_history", []))
                cycle = len(history) + (1 if resume.get("approved") is False else 0)
                handler_unit = f"direct:{direct_agent}:generation:{cycle}"
                effective_payload["_control_scope"] = handler_unit
                cached = completed_unit(job_id, handler_unit)
                if cached is not None:
                    with SessionLocal() as db:
                        current = db.get(Job, job_id)
                        result = (
                            json.loads(current.result_json)
                            if current is not None and current.result_json
                            else {}
                        )
                else:
                    result = handler(job_id, effective_payload)
                    self._store_partial_result(job_id, result)
                    checkpoint(
                        job_id,
                        "agent",
                        current_unit=handler_unit,
                        next_unit=f"direct:{direct_agent}:automatic-review",
                        message=f"{direct_agent} completado",
                        completed_unit=handler_unit,
                        result={"stored_result": True},
                    )
            else:
                result = handler(job_id, dict(payload))
            if direct_agent is not None and resume.get("approved") is not True:
                result, review_summary = _run_automatic_review(
                    job_id,
                    direct_agent,
                    handler,
                    effective_payload,
                    result,
                )
                if review_summary is not None:
                    result = {**result, "automatic_review": review_summary}
                if payload.get("human_review_enabled", False):
                    checkpoint(
                        job_id,
                        "human_approval",
                        current_unit=f"direct:{direct_agent}:review",
                        next_unit=f"direct:{direct_agent}:human-approval",
                        message=f"{direct_agent} listo para revisión humana",
                    )
                    history = list(payload.get("_human_feedback_history", []))
                    if resume.get("approved") is False:
                        history.append(
                            {
                                "cycle": len(history) + 1,
                                "feedback": resume.get("feedback", ""),
                            }
                        )
                    pending_payload = dict(payload)
                    pending_payload.pop("_resume", None)
                    pending_payload["_pending_result"] = result
                    pending_payload["_human_feedback_history"] = history
                    append_event(
                        job_id,
                        "approval_required",
                        f"Aprobación requerida para {direct_agent}",
                        {
                            "agent": direct_agent,
                            "status": "waiting_approval",
                            "result": result,
                            "human_cycles": len(history),
                        },
                    )
                    self._set_waiting(job_id, pending_payload, result)
                    return
            checkpoint(
                job_id,
                "finalizing",
                current_unit=kind,
                next_unit=None,
                message="Preparando el resultado final",
            )
            if isinstance(result, dict) and result.get("__waiting__"):
                self._set_waiting(job_id)
            else:
                if kind in MEMORY_KINDS:
                    memory_unit = f"memory:{kind}"
                    if completed_unit(job_id, memory_unit) is None:
                        checkpoint(
                            job_id,
                            "memory",
                            current_unit=None,
                            next_unit=memory_unit,
                            message="Preparando la consolidación de memoria",
                        )
                        consolidate_memory(job_id)
                        _complete_unit(
                            job_id,
                            "memory",
                            memory_unit,
                            {"completed": True},
                            message="Memoria consolidada",
                        )
                self._finish(job_id, result=result)
        except RunPaused as exc:
            append_event(
                job_id,
                "control",
                "Ejecución pausada en un punto seguro",
                {"status": "paused", "checkpoint": exc.checkpoint},
            )
        except RunCanceled as exc:
            append_event(
                job_id,
                "control",
                "Ejecución cancelada en un punto seguro",
                {"status": "canceled", "checkpoint": exc.checkpoint},
            )
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            self._finish(job_id, error=str(exc))

    def _store_partial_result(self, job_id: str, result: dict | None) -> None:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.result_json = (
                    json.dumps(result, ensure_ascii=False) if result is not None else None
                )
                db.commit()

    def _set_waiting(
        self,
        job_id: str,
        payload: dict | None = None,
        result: dict | None = None,
    ) -> None:
        checkpoint(
            job_id,
            "human_approval",
            current_unit=None,
            next_unit="human-approval",
            message="Preparando la aprobación humana",
        )
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.status = "waiting_approval"
                if payload is not None:
                    job.payload_json = json.dumps(payload, ensure_ascii=False)
                if result is not None:
                    job.result_json = json.dumps(result, ensure_ascii=False)
                db.commit()
                logger.info(
                    "Job waiting for approval",
                    extra={"job_id": job_id, "job_kind": job.kind},
                )

    def _finish(self, job_id: str, result: dict | None = None, error: str = "") -> None:
        if not error:
            checkpoint(
                job_id,
                "finalizing",
                current_unit="result",
                next_unit=None,
                message="Guardando el resultado final",
            )
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            if job.status in {"paused", "canceled"}:
                return
            job.status = "failed" if error else "done"
            job.error = error
            job.result_json = json.dumps(result, ensure_ascii=False) if result else None
            job.finished_at = datetime.now(UTC)
            db.commit()
            duration_ms = None
            if job.started_at is not None:
                started_at = job.started_at
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=UTC)
                duration_ms = round(
                    (job.finished_at - started_at).total_seconds() * 1000,
                    2,
                )
            logger.info(
                "Job execution finished",
                extra={
                    "job_id": job_id,
                    "job_kind": job.kind,
                    "job_status": job.status,
                    "duration_ms": duration_ms,
                },
            )


class BudgetExceeded(RuntimeError):
    pass


# Per-job token accounting (in-process; reset when the job starts).
_TOKENS_USED: dict[str, int] = {}


def add_tokens(job_id: str, tokens: int, *, persisted: bool = False) -> None:
    settings = get_settings()
    if persisted:
        with SessionLocal() as db:
            total = int(
                db.scalar(
                    select(func.coalesce(func.sum(UsageRecord.total_tokens), 0)).where(
                        UsageRecord.job_id == job_id
                    )
                )
                or 0
            )
    else:
        total = _TOKENS_USED.get(job_id, 0) + max(tokens, 0)
    _TOKENS_USED[job_id] = total
    estimated_usd = total / 1_000_000 * settings.budget_price_per_mtok_usd
    if settings.budget_usd_per_run > 0 and estimated_usd > settings.budget_usd_per_run:
        raise BudgetExceeded(
            f"Presupuesto del run superado: ~${estimated_usd:.2f} "
            f"(límite ${settings.budget_usd_per_run:.2f}, {total:,} tokens). "
            f"Ajusta BUDGET_USD_PER_RUN si lo necesitas."
        )


class TrackedClient:
    """Wrap the direct OpenAI-compatible client with persistent accounting."""

    def __init__(
        self,
        inner,
        job_id: str,
        *,
        agent: str = "",
        operation: str = "llm",
        work_unit_key: str = "",
        workflow_step: int | None = None,
    ):
        self._inner = inner
        self._job_id = job_id
        self._agent = agent
        self._operation = operation
        self._work_unit_key = work_unit_key
        self._workflow_step = workflow_step
        self._call_index = 0
        self.chat = type(
            "chat", (), {"completions": type("completions", (), {"create": self._create})()}
        )()

    def _create(self, **kwargs):
        response = self._inner.chat.completions.create(**kwargs)
        self._call_index += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0
            request_id = getattr(response, "id", None)
            effective_model = getattr(response, "model", None) or kwargs.get("model", "")
            usage_record_id = record_usage(
                job_id=self._job_id,
                workflow_step=self._workflow_step,
                agent=self._agent,
                operation=self._operation,
                provider="openrouter",
                model=effective_model,
                provider_request_id=request_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=getattr(usage, "cost", None),
                work_unit_key=self._work_unit_key,
                idempotency_key=(
                    None
                    if request_id
                    else (
                        f"{self._job_id}:{self._agent}:{self._operation}:"
                        f"{self._work_unit_key}:{self._call_index}"
                    )
                ),
            )
            add_tokens(
                self._job_id,
                input_tokens + output_tokens,
                persisted=usage_record_id is not None,
            )
        return response


def _client(
    job_id: str,
    *,
    agent: str = "",
    operation: str = "llm",
    work_unit_key: str = "",
    workflow_step: int | None = None,
):
    from factory_agents.llm import get_llm_client

    settings = get_settings()
    return TrackedClient(
        get_llm_client(settings.openrouter_api_key),
        job_id,
        agent=agent,
        operation=operation,
        work_unit_key=work_unit_key,
        workflow_step=workflow_step,
    )


def _budget_callbacks(
    job_id: str,
    *,
    agent: str = "",
    operation: str = "llm",
    work_unit_key: str = "",
    workflow_step: int | None = None,
) -> list:
    """LangChain callback tracking deep-agent usage and the budget."""
    from langchain_core.callbacks import BaseCallbackHandler

    class BudgetCallback(BaseCallbackHandler):
        raise_error = True
        call_index = 0

        def on_llm_end(self, response, **kwargs):
            self.call_index += 1
            seen: set[str] = set()
            recorded = False
            for generations in response.generations:
                for generation in generations:
                    message = getattr(generation, "message", None)
                    usage = getattr(message, "usage_metadata", None) or {}
                    response_metadata = getattr(message, "response_metadata", None) or {}
                    request_id = (
                        getattr(message, "id", None)
                        or response_metadata.get("id")
                        or response_metadata.get("generation_id")
                    )
                    dedupe = str(request_id or id(message))
                    if dedupe in seen:
                        continue
                    seen.add(dedupe)
                    input_tokens = usage.get("input_tokens", 0) or 0
                    output_tokens = usage.get("output_tokens", 0) or 0
                    if not (input_tokens or output_tokens):
                        continue
                    effective_model = (
                        response_metadata.get("model_name")
                        or response_metadata.get("model")
                        or ""
                    )
                    usage_record_id = record_usage(
                        job_id=job_id,
                        workflow_step=workflow_step,
                        agent=agent,
                        operation=operation,
                        provider="openrouter",
                        model=effective_model,
                        provider_request_id=request_id,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=usage.get("cost") or response_metadata.get("cost"),
                        work_unit_key=work_unit_key,
                        idempotency_key=(
                            None
                            if request_id
                            else (
                                f"{job_id}:{agent}:{operation}:{work_unit_key}:"
                                f"{self.call_index}:{len(seen)}"
                            )
                        ),
                    )
                    add_tokens(
                        job_id,
                        input_tokens + output_tokens,
                        persisted=usage_record_id is not None,
                    )
                    recorded = True
            if recorded:
                return
            llm_output = getattr(response, "llm_output", None) or {}
            token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
            input_tokens = (
                token_usage.get("prompt_tokens")
                or token_usage.get("input_tokens")
                or 0
            )
            output_tokens = (
                token_usage.get("completion_tokens")
                or token_usage.get("output_tokens")
                or 0
            )
            if input_tokens or output_tokens:
                run_id = kwargs.get("run_id")
                request_id = llm_output.get("id") or llm_output.get("generation_id")
                usage_record_id = record_usage(
                    job_id=job_id,
                    workflow_step=workflow_step,
                    agent=agent,
                    operation=operation,
                    provider="openrouter",
                    model=llm_output.get("model_name") or llm_output.get("model") or "",
                    provider_request_id=request_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=token_usage.get("cost") or llm_output.get("cost"),
                    work_unit_key=work_unit_key,
                    idempotency_key=(
                        None
                        if request_id
                        else (
                            f"{job_id}:{agent}:{operation}:{work_unit_key}:"
                            f"{run_id or self.call_index}"
                        )
                    ),
                )
                add_tokens(
                    job_id,
                    input_tokens + output_tokens,
                    persisted=usage_record_id is not None,
                )

    return [BudgetCallback()]


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
    logger.info(
        "Job event",
        extra={
            "job_id": job_id,
            "event_type": type_,
            "event_summary": summary,
            **(data or {}),
        },
    )


def _control_unit(payload: dict, phase: str, identity: str = "main") -> str:
    scope = str(payload.get("_control_scope") or f"job:{phase}")
    return f"{scope}:{phase}:{identity}"


def _before_unit(
    job_id: str,
    payload: dict,
    phase: str,
    identity: str,
    message: str,
) -> tuple[str, dict | None]:
    unit = _control_unit(payload, phase, identity)
    cached = completed_unit(job_id, unit)
    if cached is None:
        checkpoint(
            job_id,
            phase,
            current_unit=None,
            next_unit=unit,
            message=message,
        )
    return unit, cached


def _complete_unit(
    job_id: str,
    phase: str,
    unit: str,
    result: dict,
    *,
    next_unit: str | None = None,
    message: str = "",
) -> None:
    checkpoint(
        job_id,
        phase,
        current_unit=unit,
        next_unit=next_unit,
        message=message,
        completed_unit=unit,
        result=result,
    )


def _save_artifact(
    job_id: str,
    project_id: str,
    type_: str,
    title: str,
    content: str,
    format_: str = "markdown",
    metadata: dict | None = None,
) -> str:
    settings = get_settings()
    ext = {"markdown": "md", "json": "json"}.get(format_, "txt")
    # A single job can emit several artifacts of the same type (e.g. one deck
    # per lesson), so the path must be unique per artifact — otherwise every
    # deck (and its Marp renders) would overwrite the previous one and only the
    # last lesson would be downloadable.
    rel_path = f"artifacts/{project_id}/{type_}-{job_id}-{uuid.uuid4().hex[:8]}.{ext}"
    abs_path = settings.data_dir / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    with SessionLocal() as db:
        artifact_metadata_value = dict(metadata or {})
        artifact = add_artifact_version(
            db,
            project_id=project_id,
            type_=type_,
            format_=format_,
            title=title,
            path=rel_path,
            created_by_job_id=job_id,
            metadata=artifact_metadata_value,
        )
        attach_usage_to_artifact(
            db,
            artifact,
            job_id=job_id,
            agent=(
                artifact_metadata_value.get("agent")
                or artifact_metadata_value.get("duration_agent")
            ),
            usage_record_ids=artifact_metadata_value.get("usage_record_ids"),
        )
        db.commit()
        logger.info(
            "Artifact persisted",
            extra={
                "job_id": job_id,
                "project_id": project_id,
                "artifact_id": artifact.id,
                "artifact_type": type_,
                "artifact_version": artifact.version,
            },
        )
        return artifact.id


def _latest_artifact_content(project_id: str, type_: str) -> tuple[str | None, str | None]:
    """Return (artifact_id, content) of the newest artifact of a type."""
    settings = get_settings()
    with SessionLocal() as db:
        artifact = selected_artifact(db, project_id, type_)
        if artifact is None:
            return None, None
        path = settings.data_dir / artifact.path
        return artifact.id, path.read_text(encoding="utf-8") if path.is_file() else None


def _save_artifact_if_changed(
    job_id: str,
    project_id: str,
    type_: str,
    title: str,
    content: str,
    *,
    format_: str = "text",
    metadata: dict | None = None,
) -> str:
    """Reuse the selected text artifact when regeneration produced identical content."""
    settings = get_settings()
    with SessionLocal() as db:
        logical_key = artifact_logical_key(type_, title)
        current = db.scalars(
            select(Artifact).where(
                Artifact.project_id == project_id,
                Artifact.logical_key == logical_key,
                Artifact.is_selected.is_(True),
            )
        ).first()
        if current is not None:
            path = settings.data_dir / current.path
            if path.is_file() and path.read_text(encoding="utf-8") == content:
                return current.id
    return _save_artifact(
        job_id,
        project_id,
        type_,
        title,
        content,
        format_=format_,
        metadata=metadata,
    )


def _require_artifact(project_id: str, type_: str, hint: str) -> str:
    _id, content = _latest_artifact_content(project_id, type_)
    if not content:
        raise RuntimeError(f"Falta el artefacto '{type_}': {hint}")
    return content


def _duration_spec(payload: dict) -> DurationSpec | None:
    value = payload.get("duration_spec")
    return DurationSpec.model_validate(value) if value else None


def _duration_metadata(payload: dict, agent: str) -> dict:
    spec = _duration_spec(payload)
    metadata = {
        "agent": agent,
        "research_mode": payload.get("research_mode", "web_only"),
        "source_ids": list(payload.get("source_ids") or []),
    }
    if spec is not None:
        orientation = payload.get("orientation", "horizontal")
        metadata.update(
            {
                "duration_spec": spec.model_dump(),
                "duration_metrics": duration_metrics(spec, orientation),
                "duration_agent": agent,
            }
        )
    return metadata


def _project_source_documents(project_id: str, source_ids: list[str]) -> list[dict]:
    from factory_api.models import IdeationSource

    if not source_ids:
        return []
    with SessionLocal() as db:
        sources = db.scalars(
            select(IdeationSource).where(
                IdeationSource.project_id == project_id,
                IdeationSource.id.in_(source_ids),
                IdeationSource.status == "ready",
            )
        ).all()
        by_id = {source.id: source for source in sources}
        return [
            {
                "id": source_id,
                "name": by_id[source_id].name,
                "kind": by_id[source_id].kind,
                "media_type": by_id[source_id].media_type,
                "size_bytes": by_id[source_id].size_bytes,
                "text": by_id[source_id].extracted_text,
                "metadata": by_id[source_id].source_metadata,
            }
            for source_id in source_ids
            if source_id in by_id
        ]


def _emit_duration_event(job_id: str, payload: dict, agent: str) -> None:
    spec = _duration_spec(payload)
    if spec is None:
        return
    metrics = duration_metrics(spec, payload.get("orientation", "horizontal"))
    append_event(
        job_id,
        "constraints",
        (
            f"Duración congelada: {spec.total_videos} vídeos, "
            f"{spec.total_minutes} min ({spec.preset})"
        ),
        {
            "agent": agent,
            "duration_spec": spec.model_dump(),
            "duration_metrics": metrics,
        },
    )


def _emit_metric_warning(
    job_id: str, label: str, actual: int, budget: dict[str, int]
) -> None:
    if budget["min"] <= actual <= budget["max"]:
        return
    append_event(
        job_id,
        "warning",
        (
            f"{label}: {actual} frente al rango objetivo "
            f"{budget['min']}–{budget['max']}"
        ),
        {"actual": actual, **budget},
    )


def _deactivate_unproduced(project_id: str, type_: str, keep_ids: list[str]) -> None:
    """Replace a generated collection, hiding families absent from the new run."""
    keep = set(keep_ids)
    with SessionLocal() as db:
        selected = db.scalars(
            select(Artifact).where(
                Artifact.project_id == project_id,
                Artifact.type == type_,
                Artifact.is_selected.is_(True),
            )
        ).all()
        for artifact in selected:
            if artifact.id not in keep:
                artifact.is_selected = False
        db.commit()


def run_curator_job(job_id: str, payload: dict) -> dict:
    # Imported lazily so tests can monkeypatch factory_agents pieces easily.
    from factory_agents.agents.curator import run_curator

    settings = get_settings()
    workspace = settings.data_dir / "runs" / job_id
    unit, cached = _before_unit(
        job_id, payload, "curator", "brief", "Preparando el Curador"
    )
    if cached and cached.get("artifact_id"):
        return {"artifact_id": cached["artifact_id"]}
    _emit_duration_event(job_id, payload, "curator")
    spec = _duration_spec(payload)
    source_documents = _project_source_documents(
        payload["project_id"], list(payload.get("source_ids") or [])
    )
    research_mode = payload.get("research_mode", "web_only")
    if research_mode == "provided_only" and not source_documents:
        raise RuntimeError(
            "El modo «Solo fuentes proporcionadas» requiere al menos una fuente válida"
        )
    final_text = ""
    for event in run_curator(
        _augment_input(payload["task_input"], payload, "curator"),
        model=payload.get("model") or settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        tavily_api_key=settings.tavily_api_key,
        workspace_dir=str(workspace),
        soul_md=payload.get("soul_md", ""),
        agents_md=payload.get("agents_md", ""),
        recursion_limit=settings.agent_recursion_limit,
        callbacks=_budget_callbacks(
            job_id,
            agent="curator",
            work_unit_key="curator",
            workflow_step=payload.get("_workflow_step"),
        ),
        max_searches=research_budget(spec.total_minutes)["searches_max"] if spec else None,
        research_mode=research_mode,
        source_documents=source_documents,
        max_source_queries=(
            research_budget(spec.total_minutes)["searches_max"] if spec else 12
        ),
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
        metadata=_duration_metadata(payload, "curator"),
    )
    append_event(job_id, "artifact", "Research brief generado", {"artifact_id": artifact_id})
    _complete_unit(
        job_id,
        "curator",
        unit,
        {"artifact_id": artifact_id},
        message="Research brief completado",
    )
    return {"artifact_id": artifact_id}


def run_planner_job(job_id: str, payload: dict) -> dict:
    from factory_agents.agents.planner import render_planner_input, run_planner

    settings = get_settings()
    unit, cached = _before_unit(
        job_id, payload, "planner", "course-plan", "Preparando el plan del curso"
    )
    if cached and cached.get("artifact_id"):
        return {"artifact_id": cached["artifact_id"]}
    brief_md = _require_artifact(
        payload["project_id"], "research_brief", "ejecuta antes el Curador"
    )
    _emit_duration_event(job_id, payload, "planner")
    spec = _duration_spec(payload)
    append_event(job_id, "stage", "Diseñando la estructura del curso…")
    plan = run_planner(
        _augment_input(
            render_planner_input(payload.get("project", {}), brief_md),
            payload,
            "planner",
        ),
        client=_client(
            job_id,
            agent="planner",
            work_unit_key="planner",
            workflow_step=payload.get("_workflow_step"),
        ),
        model=payload.get("model") or settings.openrouter_model,
        soul_md=payload.get("soul_md", ""),
        agents_md=payload.get("agents_md", ""),
        duration_spec=spec,
    )
    if spec:
        problems = validate_course_plan_structure(plan, spec)
        if problems:
            raise RuntimeError("El plan no respeta la estructura: " + "; ".join(problems))
    artifact_id = _save_artifact(
        job_id,
        payload["project_id"],
        "course_plan",
        f"Plan del curso — {plan.course_title}",
        plan.model_dump_json(indent=2),
        format_="json",
        metadata=_duration_metadata(payload, "planner"),
    )
    total = sum(len(m.lessons) for m in plan.modules)
    append_event(
        job_id,
        "artifact",
        f"Plan generado: {len(plan.modules)} módulos, {total} lecciones",
        {"artifact_id": artifact_id},
    )
    _complete_unit(
        job_id,
        "planner",
        unit,
        {"artifact_id": artifact_id},
        message="Plan del curso completado",
    )
    return {"artifact_id": artifact_id}


def run_lessons_job(job_id: str, payload: dict) -> dict:
    from factory_agents.agents.lessons import render_lesson_input, run_lesson
    from factory_agents.contracts import CoursePlan

    settings = get_settings()
    plan_json = _require_artifact(
        payload["project_id"], "course_plan", "ejecuta antes el Diseñador de curso"
    )
    brief_md = _require_artifact(
        payload["project_id"], "research_brief", "ejecuta antes el Curador"
    )
    plan = CoursePlan.model_validate_json(plan_json)
    _emit_duration_event(job_id, payload, "lessons")
    spec = _duration_spec(payload)
    if spec:
        problems = validate_course_plan_structure(plan, spec)
        if problems:
            raise RuntimeError(
                "El plan seleccionado no respeta la estructura: " + "; ".join(problems)
            )
    metrics = (
        duration_metrics(spec, payload.get("orientation", "horizontal"))
        if spec
        else None
    )

    lesson_units = list(plan.iter_lessons())
    artifact_ids: list[str] = []
    for index, (mi, li, _module, lesson) in enumerate(lesson_units):
        label = f"{mi}.{li} {lesson.title}"
        unit, cached = _before_unit(
            job_id,
            payload,
            "lessons",
            f"{mi}-{li}",
            f"Preparando la lección {label}",
        )
        if cached and cached.get("artifact_id"):
            artifact_ids.append(cached["artifact_id"])
            continue
        append_event(job_id, "stage", f"Escribiendo lección {label}…")
        final_text = ""
        for event in run_lesson(
            _augment_input(
                render_lesson_input(plan, mi, li, brief_md), payload, "lessons"
            ),
            model=payload.get("model") or settings.openrouter_model,
            api_key=settings.openrouter_api_key,
            workspace_dir=str(settings.data_dir / "runs" / job_id / f"lesson-{mi}-{li}"),
            soul_md=payload.get("soul_md", ""),
            agents_md=payload.get("agents_md", ""),
            recursion_limit=settings.agent_recursion_limit,
            callbacks=_budget_callbacks(
                job_id,
                agent="lessons",
                work_unit_key=f"lesson:{mi}.{li}",
                workflow_step=payload.get("_workflow_step"),
            ),
        ):
            if event.type == "result":
                final_text = event.summary
            elif event.type == "tool_call":
                append_event(job_id, event.type, f"[{label}] {event.summary}", event.data)
        if not final_text.strip():
            raise RuntimeError(f"La lección {label} quedó vacía")
        if metrics:
            _emit_metric_warning(
                job_id,
                f"Extensión de {label}",
                len(final_text.split()),
                metrics["lesson_words"],
            )
        artifact_id = _save_artifact(
            job_id,
            payload["project_id"],
            "lesson_content",
            label,
            final_text,
            metadata=_duration_metadata(payload, "lessons"),
        )
        artifact_ids.append(artifact_id)
        append_event(job_id, "artifact", f"Lección {label} lista", {"artifact_id": artifact_id})
        next_unit = (
            _control_unit(
                payload,
                "lessons",
                f"{lesson_units[index + 1][0]}-{lesson_units[index + 1][1]}",
            )
            if index + 1 < len(lesson_units)
            else None
        )
        _complete_unit(
            job_id,
            "lessons",
            unit,
            {"artifact_id": artifact_id},
            next_unit=next_unit,
            message=f"Lección {label} completada",
        )

    _deactivate_unproduced(payload["project_id"], "lesson_content", artifact_ids)
    return {"artifact_ids": artifact_ids}


def run_slides_job(job_id: str, payload: dict) -> dict:
    from factory_agents.agents.slides import render_slides_input, run_slides
    from factory_agents.contracts import CoursePlan
    from factory_agents.tools.images import generate_deck_images, parse_image_slots
    from factory_agents.tools.logos import apply_slide_logo
    from factory_agents.tools.marp import marp_available, render_deck
    from factory_agents.tools.palette import (
        apply_slide_palette,
        normalize_palette,
        palette_contrast,
        palette_preset_name,
        palette_warnings,
    )

    settings = get_settings()
    plan_json = _require_artifact(
        payload["project_id"], "course_plan", "ejecuta antes el Diseñador de curso"
    )
    plan = CoursePlan.model_validate_json(plan_json)
    _emit_duration_event(job_id, payload, "slides")
    duration_spec = _duration_spec(payload)
    if duration_spec:
        problems = validate_course_plan_structure(plan, duration_spec)
        if problems:
            raise RuntimeError(
                "El plan seleccionado no respeta la estructura: " + "; ".join(problems)
            )
    client = _client(
        job_id,
        agent="slides",
        work_unit_key="slides",
        workflow_step=payload.get("_workflow_step"),
    )

    with SessionLocal() as db:
        lesson_artifacts = db.scalars(
            select(Artifact)
            .where(
                Artifact.project_id == payload["project_id"],
                Artifact.type == "lesson_content",
                Artifact.is_selected.is_(True),
            )
            .order_by(Artifact.created_at)
        ).all()
        # Newest artifact per lesson title wins (lessons can be regenerated).
        by_title = {a.title: (a.id, a.path) for a in lesson_artifacts}
    if not by_title:
        raise RuntimeError(
            "Falta el artefacto 'lesson_content': ejecuta antes el Generador de lecciones"
        )

    if not marp_available():
        append_event(
            job_id,
            "stage",
            "marp-cli no está instalado: se generará solo el Markdown de las slides",
        )

    orientation = payload.get("orientation", "horizontal")
    width, height = ((1080, 1920) if orientation == "vertical" else (1920, 1080))
    images_enabled = bool(payload.get("images_enabled", False))
    image_model = payload.get("image_model", "bytedance-seed/seedream-4.5")
    image_style = payload.get("image_style", "editorial_vector")
    image_style_prompt = payload.get("image_style_prompt", "")
    slide_logo = payload.get("slide_logo")
    logo_source = None
    if isinstance(slide_logo, dict):
        from factory_api.logo_assets import stored_logo_path

        logo_source = stored_logo_path(str(slide_logo.get("path", "")))
        if logo_source is None:
            raise RuntimeError(
                "El logo congelado del perfil ya no est\u00e1 disponible; "
                "selecciona otro candidato antes de ejecutar Slides"
            )
    slide_palette = normalize_palette(payload.get("slide_palette"))
    palette_name = palette_preset_name(slide_palette)
    contrast_warnings = palette_warnings(slide_palette)
    append_event(
        job_id,
        "stage",
        f"Paleta congelada para el run: {palette_name}",
        {
            "palette_name": palette_name,
            "slide_palette": slide_palette,
            "contrast_warnings": contrast_warnings,
        },
    )
    artifact_ids: list[str] = []
    for title, (lesson_id, rel_path) in by_title.items():
        deck_unit, cached_deck = _before_unit(
            job_id,
            payload,
            "slides",
            lesson_id,
            f"Preparando las slides de {title}",
        )
        render_identity = f"{lesson_id}:render"
        render_unit = _control_unit(payload, "slides", render_identity)
        if cached_deck and cached_deck.get("artifact_id"):
            artifact_id = cached_deck["artifact_id"]
            render_cached = completed_unit(job_id, render_unit)
            rendered = list(render_cached.get("rendered", [])) if render_cached else []
            if render_cached is None:
                with SessionLocal() as db:
                    artifact = db.get(Artifact, artifact_id)
                    if artifact is None:
                        raise RuntimeError(
                            f"Las slides completadas de {title} ya no están disponibles"
                        )
                    deck_path = settings.data_dir / artifact.path
                checkpoint(
                    job_id,
                    "slides",
                    current_unit=deck_unit,
                    next_unit=render_unit,
                    message=f"Preparando el render de {title}",
                )
                rendered = render_deck(deck_path)
                _complete_unit(
                    job_id,
                    "slides",
                    render_unit,
                    {"rendered": rendered},
                    message=f"Render de {title} completado",
                )
            artifact_ids.append(artifact_id)
            append_event(
                job_id,
                "artifact",
                f"Slides de {title} recuperadas"
                + (f" (render: {', '.join(rendered)})" if rendered else ""),
                {"artifact_id": artifact_id, "resumed": True},
            )
            continue
        append_event(job_id, "stage", f"Diseñando slides de {title}…")
        lesson_md = (settings.data_dir / rel_path).read_text(encoding="utf-8")
        palette_instruction = (
            "\n\nPaleta visual obligatoria (la aplicación final será programática):\n"
            + json.dumps(slide_palette, ensure_ascii=False)
        )
        deck = run_slides(
            _augment_input(
                render_slides_input(
                    lesson_md,
                    plan.course_title,
                    payload.get("style", ""),
                    orientation,
                )
                + palette_instruction,
                payload,
                "slides",
            ),
            client=client,
            model=payload.get("model") or settings.openrouter_model,
            soul_md=payload.get("soul_md", ""),
            agents_md=payload.get("agents_md", ""),
            orientation=orientation,
            images_enabled=images_enabled,
        )
        deck = apply_slide_palette(deck, slide_palette)
        spec = _duration_spec(payload)
        if spec:
            _emit_metric_warning(
                job_id,
                f"Número de slides de {title}",
                max(1, deck.count("\n---\n")),
                duration_metrics(spec, orientation)["slides"],
            )
        image_records: list[dict] = []
        asset_dir_name = f"slide-assets-{job_id}-{uuid.uuid4().hex[:8]}"
        storage_asset_dir = f"artifacts/{payload['project_id']}/{asset_dir_name}"
        output_dir = settings.data_dir / storage_asset_dir
        if images_enabled:
            slots = parse_image_slots(deck)
            if not slots:
                append_event(
                    job_id,
                    "warning",
                    f"El agente no seleccionó imágenes para {title}",
                    {"lesson": title},
                )
            deck, image_records = generate_deck_images(
                deck,
                api_key=settings.openrouter_api_key,
                model=image_model,
                style=image_style,
                custom_style_prompt=image_style_prompt,
                orientation=orientation,
                deck_identity=f"{plan.course_title}:{title}",
                output_dir=output_dir,
                markdown_asset_dir=asset_dir_name,
                storage_asset_dir=storage_asset_dir,
                on_event=lambda event_type, summary, data, lesson_title=title: append_event(
                    job_id, event_type, f"[{lesson_title}] {summary}", data
                ),
            )
            for image in image_records:
                if image.get("status") != "generated":
                    continue
                record_usage(
                    job_id=job_id,
                    workflow_step=payload.get("_workflow_step"),
                    agent="slides",
                    operation="image",
                    provider="openrouter",
                    model=str(image.get("model") or image_model),
                    image_count=1,
                    cost_usd=image.get("cost_usd"),
                    work_unit_key=f"slides:{title}:image:{image.get('id', '')}",
                    idempotency_key=(
                        f"{job_id}:slides:{title}:image:{image.get('id', '')}"
                    ),
                    metadata={
                        "seed": image.get("seed"),
                        "style": image.get("style"),
                    },
                )
        logo_record = None
        if logo_source is not None and isinstance(slide_logo, dict):
            output_dir.mkdir(parents=True, exist_ok=True)
            logo_filename = f"brand-logo{logo_source.suffix.lower()}"
            logo_target = output_dir / logo_filename
            shutil.copy2(logo_source, logo_target)
            markdown_path = f"{asset_dir_name}/{logo_filename}"
            configured_margin = int(slide_logo.get("margin_px", 32))
            configured_placement = str(slide_logo.get("placement", "top-right"))
            safe_margin = (
                72
                if orientation == "vertical" and configured_placement.startswith("bottom")
                else 48
                if configured_placement.startswith("bottom")
                else 36
                if orientation == "vertical"
                else 24
            )
            logo_record = {
                "source_logo_id": slide_logo.get("id"),
                "source": slide_logo.get("source"),
                "name": slide_logo.get("name"),
                "media_type": slide_logo.get("media_type"),
                "width": slide_logo.get("width"),
                "height": slide_logo.get("height"),
                "sha256": slide_logo.get("sha256"),
                "prompt": slide_logo.get("prompt"),
                "model": slide_logo.get("model"),
                "seed": slide_logo.get("seed"),
                "cost_usd": slide_logo.get("cost_usd"),
                "profile_id": payload.get("profile_id"),
                "profile_version": payload.get("profile_version"),
                "mode": slide_logo.get("mode"),
                "placement": configured_placement,
                "size": slide_logo.get("size", "small"),
                "configured_margin_px": configured_margin,
                "margin_px": max(configured_margin, safe_margin),
                "opacity": float(slide_logo.get("opacity", 1.0)),
                "visibility": slide_logo.get("visibility")
                or {"cover": True, "content": True, "summary": True},
                "path": f"{storage_asset_dir}/{logo_filename}",
                "markdown_path": markdown_path,
            }
            deck = apply_slide_logo(
                deck,
                markdown_path,
                orientation=orientation,
                placement=logo_record["placement"],
                size=logo_record["size"],
                margin_px=logo_record["margin_px"],
                opacity=logo_record["opacity"],
                visibility=logo_record["visibility"],
                alt=logo_record.get("name") or "Logo de marca",
            )
            append_event(
                job_id,
                "stage",
                f"Logo congelado aplicado a {title}",
                {
                    "lesson": title,
                    "logo_id": logo_record["source_logo_id"],
                    "profile_version": payload.get("profile_version"),
                },
            )
        generation_cost = sum(
            float(item["cost_usd"])
            for item in image_records
            if item.get("cost_usd") is not None
        )
        logo_usage_id = None
        if isinstance(slide_logo, dict) and slide_logo.get("source") == "generated":
            logo_usage_id = usage_record_by_work_unit(
                f"profile-logo:{payload.get('profile_id')}:{slide_logo.get('id')}"
            )
        artifact_id = _save_artifact(
            job_id,
            payload["project_id"],
            "slide_deck",
            f"Slides — {title}",
            deck,
            metadata={
                **_duration_metadata(payload, "slides"),
                "orientation": orientation,
                "width": width,
                "height": height,
                "slide_palette": slide_palette,
                "palette_name": palette_name,
                "palette_contrast": palette_contrast(slide_palette),
                "palette_warnings": contrast_warnings,
                "images": image_records,
                "logo": logo_record,
                "usage_record_ids": [logo_usage_id] if logo_usage_id else [],
                "image_generation": {
                    "enabled": images_enabled,
                    "model": image_model if images_enabled else None,
                    "style": image_style if images_enabled else None,
                    "style_prompt": image_style_prompt if image_style == "custom" else "",
                    "max_images": 6,
                    "generated": sum(
                        item.get("status") == "generated" for item in image_records
                    ),
                    "attempted": len(image_records),
                    "generation_cost_usd": generation_cost,
                },
            },
        )
        _complete_unit(
            job_id,
            "slides",
            deck_unit,
            {"artifact_id": artifact_id},
            next_unit=render_unit,
            message=f"Deck de {title} generado",
        )
        with SessionLocal() as db:
            artifact = db.get(Artifact, artifact_id)
            deck_path = settings.data_dir / artifact.path
        checkpoint(
            job_id,
            "slides",
            current_unit=deck_unit,
            next_unit=render_unit,
            message=f"Preparando el render de {title}",
        )
        rendered = render_deck(deck_path)
        _complete_unit(
            job_id,
            "slides",
            render_unit,
            {"rendered": rendered},
            message=f"Render de {title} completado",
        )
        artifact_ids.append(artifact_id)
        append_event(
            job_id,
            "artifact",
            f"Slides de {title} listas" + (f" (render: {', '.join(rendered)})" if rendered else ""),
            {"artifact_id": artifact_id},
        )

    _deactivate_unproduced(payload["project_id"], "slide_deck", artifact_ids)
    return {"artifact_ids": artifact_ids}


def run_pipeline_job(job_id: str, payload: dict) -> dict:
    """Run the fixed chain through the same resumable workflow engine."""
    stages = payload.get("stages", {})
    definition = {
        "steps": [
            {"agent": agent, "overrides": stages.get(agent, {})}
            for agent in ("curator", "planner", "lessons", "slides")
        ]
    }
    return run_workflow_job(job_id, {**payload, "definition": definition})


def _register_artifact_file(
    job_id: str,
    project_id: str,
    type_: str,
    title: str,
    src_path,
    format_: str,
    metadata: dict | None = None,
) -> str:
    """Register an already-produced binary/text file as an artifact."""
    import shutil
    from pathlib import Path

    settings = get_settings()
    src_path = Path(src_path)
    rel_path = (
        f"artifacts/{project_id}/{type_}-{job_id}-{uuid.uuid4().hex[:8]}-{src_path.name}"
    )
    dst = settings.data_dir / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_path, dst)
    with SessionLocal() as db:
        metadata_value = dict(metadata or {})
        artifact = add_artifact_version(
            db,
            project_id=project_id,
            type_=type_,
            format_=format_,
            title=title,
            path=rel_path,
            created_by_job_id=job_id,
            metadata=metadata_value,
        )
        attach_usage_to_artifact(
            db,
            artifact,
            job_id=job_id,
            agent=metadata_value.get("agent") or metadata_value.get("duration_agent"),
            usage_record_ids=metadata_value.get("usage_record_ids"),
        )
        db.commit()
        return artifact.id


PREFIXES = {
    "slide_deck": "Slides — ",
    "teaching_script": "Guion — ",
    "voice_script": "Voz — ",
    "video": "Vídeo — ",
    "subtitles": "Subtítulos — ",
    "publication_package": "Publicación — ",
    "thumbnail": "Miniatura — ",
}


def _latest_by_base(project_id: str, type_: str) -> dict[str, "Artifact"]:
    """Latest artifact of a type per base lesson label (prefix stripped)."""
    prefix = PREFIXES.get(type_, "")
    with SessionLocal() as db:
        artifacts = db.scalars(
            select(Artifact)
            .where(
                Artifact.project_id == project_id,
                Artifact.type == type_,
                Artifact.is_selected.is_(True),
            )
            .order_by(Artifact.created_at)
        ).all()
        db.expunge_all()
    result: dict[str, Artifact] = {}
    for artifact in artifacts:
        base = artifact.title.removeprefix(prefix)
        result[base] = artifact
    return result


def run_script_job(job_id: str, payload: dict) -> dict:
    from factory_agents.agents.script import render_script_input, run_script

    settings = get_settings()
    decks = _latest_by_base(payload["project_id"], "slide_deck")
    if not decks:
        raise RuntimeError("Falta el artefacto 'slide_deck': genera o sube slides primero")
    lessons = _latest_by_base(payload["project_id"], "lesson_content")
    client = _client(
        job_id,
        agent="script",
        work_unit_key="script",
        workflow_step=payload.get("_workflow_step"),
    )
    _emit_duration_event(job_id, payload, "script")
    spec = _duration_spec(payload)

    artifact_ids: list[str] = []
    for base, deck in decks.items():
        unit, cached = _before_unit(
            job_id,
            payload,
            "script",
            deck.id,
            f"Preparando el guion docente de {base}",
        )
        if cached and cached.get("artifact_id"):
            artifact_ids.append(cached["artifact_id"])
            continue
        append_event(job_id, "stage", f"Escribiendo guion docente de {base}…")
        deck_md = (settings.data_dir / deck.path).read_text(encoding="utf-8")
        lesson = lessons.get(base)
        lesson_md = (
            (settings.data_dir / lesson.path).read_text(encoding="utf-8") if lesson else None
        )
        script_md = run_script(
            _augment_input(
                render_script_input(deck_md, lesson_md, payload.get("project_title", "")),
                payload,
                "script",
            ),
            client=client,
            model=payload.get("model") or settings.openrouter_model,
            soul_md=payload.get("soul_md", ""),
            agents_md=payload.get("agents_md", ""),
        )
        if spec:
            _emit_metric_warning(
                job_id,
                f"Extensión del guion de {base}",
                len(script_md.split()),
                duration_metrics(spec)["narration_words"],
            )
        artifact_id = _save_artifact(
            job_id,
            payload["project_id"],
            "teaching_script",
            f"Guion — {base}",
            script_md,
            metadata=_duration_metadata(payload, "script"),
        )
        artifact_ids.append(artifact_id)
        append_event(job_id, "artifact", f"Guion de {base} listo", {"artifact_id": artifact_id})
        _complete_unit(
            job_id,
            "script",
            unit,
            {"artifact_id": artifact_id},
            message=f"Guion docente de {base} completado",
        )
    _deactivate_unproduced(payload["project_id"], "teaching_script", artifact_ids)
    return {"artifact_ids": artifact_ids}


def run_voice_job(job_id: str, payload: dict) -> dict:
    from factory_agents.agents.voice import render_voice_input, run_voice
    from factory_agents.tools.tts import default_tts_config, resolve_tts_config

    settings = get_settings()
    scripts = _latest_by_base(payload["project_id"], "teaching_script")
    if not scripts:
        raise RuntimeError(
            "Falta el artefacto 'teaching_script': ejecuta antes el Guionista docente"
        )
    client = _client(
        job_id,
        agent="voice",
        work_unit_key="voice",
        workflow_step=payload.get("_workflow_step"),
    )
    language = payload.get("project", {}).get("language", "es")
    tts_candidate = payload.get("tts_config") or default_tts_config(
        model=settings.tts_model,
        voice=settings.tts_voice,
    )
    try:
        tts_config = resolve_tts_config(
            tts_candidate,
            project_language=language,
        )
    except ValueError as exc:
        raise RuntimeError(
            f"La configuración TTS del perfil Voice no es compatible con "
            f"el idioma del proyecto ({language}): {exc}"
        ) from exc
    _emit_duration_event(job_id, payload, "voice")
    spec = _duration_spec(payload)

    artifact_ids: list[str] = []
    for base, script in scripts.items():
        unit, cached = _before_unit(
            job_id,
            payload,
            "voice",
            script.id,
            f"Preparando el guion de voz de {base}",
        )
        if cached and cached.get("artifact_id"):
            artifact_ids.append(cached["artifact_id"])
            continue
        append_event(job_id, "stage", f"Adaptando a voz {base}…")
        script_md = (settings.data_dir / script.path).read_text(encoding="utf-8")
        voice_script = run_voice(
            _augment_input(
                render_voice_input(script_md, base, language), payload, "voice"
            ),
            client=client,
            model=payload.get("model") or settings.openrouter_model,
            soul_md=payload.get("soul_md", ""),
            agents_md=payload.get("agents_md", ""),
        )
        if spec:
            _emit_metric_warning(
                job_id,
                f"Extensión de voz de {base}",
                sum(len(segment.text.split()) for segment in voice_script.segments),
                duration_metrics(spec)["narration_words"],
            )
        artifact_id = _save_artifact(
            job_id,
            payload["project_id"],
            "voice_script",
            f"Voz — {base}",
            voice_script.model_dump_json(indent=2),
            format_="json",
            metadata={
                **_duration_metadata(payload, "voice"),
                "llm_model": payload.get("model") or settings.openrouter_model,
                "tts": {
                    **tts_config,
                    "profile_id": payload.get("profile_id"),
                    "profile_version": payload.get("profile_version"),
                    "llm_model": payload.get("model") or settings.openrouter_model,
                },
            },
        )
        artifact_ids.append(artifact_id)
        append_event(
            job_id,
            "artifact",
            f"Guion de voz de {base} listo ({len(voice_script.segments)} segmentos)",
            {"artifact_id": artifact_id},
        )
        _complete_unit(
            job_id,
            "voice",
            unit,
            {"artifact_id": artifact_id},
            message=f"Guion de voz de {base} completado",
        )
    _deactivate_unproduced(payload["project_id"], "voice_script", artifact_ids)
    return {"artifact_ids": artifact_ids}


def run_video_job(job_id: str, payload: dict) -> dict:
    from factory_agents.contracts import VoiceScript
    from factory_agents.tools.tts import (
        build_tts_provider,
        default_tts_config,
        estimated_tts_cost,
        resolve_tts_config,
        synthesize_cached_with_status,
    )
    from factory_agents.tools.video import (
        build_srt,
        burn_subtitles,
        compose_video,
        probe_duration,
        render_slide_images,
    )

    settings = get_settings()
    voices = _latest_by_base(payload["project_id"], "voice_script")
    decks = _latest_by_base(payload["project_id"], "slide_deck")
    if not voices:
        raise RuntimeError("Falta el artefacto 'voice_script': ejecuta antes el Adaptador de voz")

    cache_dir = settings.data_dir / "tts-cache"
    workdir_root = settings.data_dir / "runs" / job_id
    orientation = payload.get("orientation", "horizontal")
    subtitles_mode = payload.get("subtitles_mode", "none")
    width, height = ((1080, 1920) if orientation == "vertical" else (1920, 1080))
    _emit_duration_event(job_id, payload, "video")
    spec = _duration_spec(payload)

    video_ids: list[str] = []
    subtitle_ids: list[str] = []
    for base, voice_artifact in voices.items():
        lesson_unit, cached_lesson = _before_unit(
            job_id,
            payload,
            "video",
            voice_artifact.id,
            f"Preparando el vídeo de {base}",
        )
        if cached_lesson and cached_lesson.get("video_id"):
            video_ids.append(cached_lesson["video_id"])
            if cached_lesson.get("subtitles_id"):
                subtitle_ids.append(cached_lesson["subtitles_id"])
            continue
        deck = decks.get(base)
        if deck is None:
            raise RuntimeError(f"No hay slide_deck para «{base}»: regenera las slides")
        workdir = workdir_root / base.replace("/", "_").replace(" ", "_")[:60]

        render_unit, cached_render = _before_unit(
            job_id,
            payload,
            "video-render",
            voice_artifact.id,
            f"Preparando el render de slides de {base}",
        )
        images = (
            [Path(value) for value in cached_render.get("images", [])]
            if cached_render
            else []
        )
        if not images or not all(image.is_file() for image in images):
            append_event(job_id, "stage", f"Renderizando slides de {base} a imágenes…")
            images = render_slide_images(settings.data_dir / deck.path, workdir / "slides")
            _complete_unit(
                job_id,
                "video-render",
                render_unit,
                {"images": [str(image) for image in images]},
                message=f"Slides de {base} renderizadas",
            )

        voice_script = VoiceScript.model_validate_json(
            (settings.data_dir / voice_artifact.path).read_text(encoding="utf-8")
        )
        voice_metadata = artifact_metadata(voice_artifact)
        tts_candidate = voice_metadata.get("tts") or default_tts_config(
            model=settings.tts_model,
            voice=settings.tts_voice,
        )
        try:
            tts_config = resolve_tts_config(
                tts_candidate,
                project_language=payload.get("project", {}).get("language", "es"),
            )
        except ValueError as exc:
            raise RuntimeError(
                f"El voice_script seleccionado para «{base}» tiene una "
                f"configuración TTS no disponible: {exc}"
            ) from exc
        provider = build_tts_provider(
            tts_config,
            openai_api_key=settings.openai_api_key,
            openrouter_api_key=settings.openrouter_api_key,
        )
        append_event(
            job_id,
            "stage",
            f"Sintetizando narración de {base} ({len(voice_script.segments)} segmentos)…",
        )
        pairs: list[tuple] = []
        srt_segments: list[tuple[str, float]] = []
        for segment_index, segment in enumerate(voice_script.segments, start=1):
            segment_unit, cached_segment = _before_unit(
                job_id,
                payload,
                "tts",
                f"{voice_artifact.id}:{segment_index}",
                f"Preparando segmento {segment_index} de {base}",
            )
            cached_audio = (
                Path(cached_segment["audio_path"])
                if cached_segment and cached_segment.get("audio_path")
                else None
            )
            reused_control_unit = cached_audio is not None and cached_audio.is_file()
            if reused_control_unit:
                audio = cached_audio
                cache_hit = True
            else:
                audio, cache_hit = synthesize_cached_with_status(
                    provider, segment.text, cache_dir
                )
            record_usage(
                job_id=job_id,
                workflow_step=payload.get("_workflow_step"),
                agent="video",
                operation="tts",
                provider=tts_config["tts_provider"],
                model=tts_config["tts_model"],
                provider_request_id=(
                    None if cache_hit else getattr(provider, "last_generation_id", None)
                ),
                input_characters=len(segment.text),
                cost_usd=(
                    0
                    if cache_hit
                    else estimated_tts_cost(tts_config, len(segment.text))
                ),
                cost_source=(
                    "provider_actual"
                    if cache_hit
                    else (
                        "estimated_catalog"
                        if estimated_tts_cost(tts_config, len(segment.text)) is not None
                        else "unknown"
                    )
                ),
                pricing_snapshot={
                    "currency": "USD",
                    "cache_hit": cache_hit,
                    "price_per_million_characters_usd": tts_config.get(
                        "price_per_million_characters_usd"
                    ),
                },
                work_unit_key=f"video:{base}:tts:{segment_index}",
                idempotency_key=f"{job_id}:video:{base}:tts:{segment_index}",
                metadata={
                    "language": tts_config["tts_language_effective"],
                    "voice": tts_config["tts_voice"],
                    "cache_hit": cache_hit,
                    "segment": segment_index,
                },
            )
            if not reused_control_unit:
                _complete_unit(
                    job_id,
                    "tts",
                    segment_unit,
                    {"audio_path": str(audio)},
                    message=f"Segmento {segment_index} de {base} sintetizado",
                )
            image = images[min(segment.slide, len(images)) - 1]
            pairs.append((image, audio))
            srt_segments.append((segment.text, probe_duration(audio)))
        duration = sum(value for _text, value in srt_segments)
        target_seconds = spec.target_minutes_per_video * 60 if spec else None
        deviation_ratio = (
            abs(duration - target_seconds) / target_seconds if target_seconds else None
        )

        compose_unit, cached_compose = _before_unit(
            job_id,
            payload,
            "video-compose",
            voice_artifact.id,
            f"Preparando el montaje ffmpeg de {base}",
        )
        srt_content = build_srt(srt_segments)
        srt_path = workdir / "subtitles.srt"
        if subtitles_mode != "none":
            srt_path.parent.mkdir(parents=True, exist_ok=True)
            srt_path.write_text(srt_content, encoding="utf-8")
        out_mp4 = (
            Path(cached_compose["video_path"])
            if cached_compose and cached_compose.get("video_path")
            else workdir / "lesson.mp4"
        )
        subtitle_style = (
            cached_compose.get("subtitle_style") if cached_compose else None
        )
        if cached_compose is None or not out_mp4.is_file():
            append_event(
                job_id,
                "stage",
                f"Montando vídeo {orientation} de {base} (ffmpeg)…",
            )
            out_mp4 = workdir / "lesson.mp4"
            compose_video(pairs, out_mp4, workdir / "segments", orientation=orientation)
            if subtitles_mode == "burned_and_srt":
                append_event(job_id, "stage", f"Incrustando subtítulos de {base}…")
                out_mp4, subtitle_style = burn_subtitles(
                    out_mp4,
                    srt_path,
                    workdir / "lesson-subtitled.mp4",
                    orientation=orientation,
                    logo_metadata=(artifact_metadata(deck).get("logo") or {}),
                )
            record_usage(
                job_id=job_id,
                workflow_step=payload.get("_workflow_step"),
                agent="video",
                operation="other",
                provider="local",
                model="ffmpeg",
                cost_usd=0,
                cost_source="provider_actual",
                work_unit_key=f"video:{base}:ffmpeg",
                idempotency_key=f"{job_id}:video:{base}:ffmpeg",
                metadata={"local_operation": True},
            )
            _complete_unit(
                job_id,
                "video-compose",
                compose_unit,
                {
                    "video_path": str(out_mp4),
                    "subtitle_style": subtitle_style,
                },
                message=f"Montaje ffmpeg de {base} completado",
            )

        srt_id = None
        if subtitles_mode != "none":
            srt_id = _save_artifact_if_changed(
                job_id,
                payload["project_id"],
                "subtitles",
                f"Subtítulos — {base}",
                srt_content,
                format_="text",
                metadata={
                    **_duration_metadata(payload, "video"),
                    "voice_script_id": voice_artifact.id,
                    "duration_seconds": duration,
                    "subtitles_mode": subtitles_mode,
                    "tts": tts_config,
                },
            )
            subtitle_ids.append(srt_id)
        video_id = _register_artifact_file(
            job_id,
            payload["project_id"],
            "video",
            f"Vídeo — {base}",
            out_mp4,
            "video",
            metadata={
                **_duration_metadata(payload, "video"),
                "orientation": orientation,
                "width": width,
                "height": height,
                "slide_orientation": artifact_metadata(deck).get(
                    "orientation", "horizontal"
                ),
                "slide_deck_id": deck.id,
                "voice_script_id": voice_artifact.id,
                "tts": tts_config,
                "subtitles_mode": subtitles_mode,
                "subtitles_id": srt_id,
                "subtitles_style": subtitle_style,
                "duration_seconds": duration,
                "target_duration_seconds": target_seconds,
                "duration_deviation_ratio": deviation_ratio,
                "duration_within_tolerance": (
                    deviation_ratio <= spec.tolerance_ratio
                    if deviation_ratio is not None and spec is not None
                    else None
                ),
            },
        )
        video_ids.append(video_id)
        if deviation_ratio is not None and spec and deviation_ratio > spec.tolerance_ratio:
            append_event(
                job_id,
                "warning",
                (
                    f"Duración real de {base}: {duration / 60:.1f} min; "
                    f"objetivo {spec.target_minutes_per_video} min (fuera de ±20 %)"
                ),
                {
                    "duration_seconds": duration,
                    "target_duration_seconds": target_seconds,
                    "deviation_ratio": deviation_ratio,
                },
            )
        append_event(
            job_id,
            "artifact",
            f"Vídeo {orientation} de {base} listo ({duration / 60:.1f} min)",
            {
                "artifact_id": video_id,
                "subtitles_id": srt_id,
                "orientation": orientation,
                "subtitles_mode": subtitles_mode,
            },
        )
        _complete_unit(
            job_id,
            "video",
            lesson_unit,
            {"video_id": video_id, "subtitles_id": srt_id},
            message=f"Vídeo de {base} completado",
        )
    _deactivate_unproduced(payload["project_id"], "video", video_ids)
    _deactivate_unproduced(payload["project_id"], "subtitles", subtitle_ids)
    return {"artifact_ids": video_ids}


def _wiki_context(project_id: str) -> str:
    """Render the project wiki (plus user memory) as a prompt section."""
    from factory_agents.memory import render_wiki_for_prompt

    from factory_api.models import WikiPage

    with SessionLocal() as db:
        pages = db.scalars(
            select(WikiPage)
            .where((WikiPage.project_id == project_id) | (WikiPage.project_id.is_(None)))
            .order_by(WikiPage.updated_at)
        ).all()
        data = [{"slug": p.slug, "title": p.title, "content_md": p.content_md} for p in pages]
    return render_wiki_for_prompt(data)


def _with_wiki(task_input: str, project_id: str) -> str:
    wiki = _wiki_context(project_id)
    return f"{task_input}\n\n{wiki}" if wiki else task_input


def _augment_input(task_input: str, payload: dict, agent: str | None = None) -> str:
    """Attach wiki memory and (when revising) the evaluator feedback."""
    parts = [_with_wiki(task_input, payload["project_id"])]
    spec = _duration_spec(payload)
    if agent and spec:
        parts.append(
            render_duration_constraints(
                spec,
                agent,
                orientation=payload.get("orientation", "horizontal"),
            )
        )
    if agent:
        research_mode = payload.get("research_mode", "web_only")
        source_ids = list(payload.get("source_ids") or [])
        policy = [
            "# Procedencia de investigación congelada",
            f"- Modo: {research_mode}",
            f"- IDs del corpus: {', '.join(source_ids) if source_ids else 'ninguno'}",
            "- Conserva las citas y la procedencia trazable del research brief.",
        ]
        if research_mode == "provided_only":
            if agent == "curator":
                policy.append(
                    "- Interpreta el presupuesto de búsquedas como consultas al corpus, "
                    "fuentes relevantes mínimas y extensión máxima; nunca como permiso web."
                )
            else:
                policy.append(
                    "- No introduzcas afirmaciones factuales externas al research brief; "
                    "mantén visibles los huecos no cubiertos por las fuentes."
                )
        parts.append("\n".join(policy))
    feedback = payload.get("revision_feedback")
    if feedback:
        parts.append(
            "# Feedback del evaluador (versión anterior rechazada — corrige esto)\n\n" + feedback
        )
    return "\n\n".join(parts)


def consolidate_memory(job_id: str) -> None:
    """Librarian pass after a successful job (best-effort, never raises)."""
    from factory_agents.memory import run_librarian

    from factory_api.models import WikiPage

    settings = get_settings()
    if not settings.openrouter_api_key:
        return
    try:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None or job.project_id is None:
                return
            project_id = job.project_id
            artifacts = db.scalars(
                select(Artifact)
                .where(Artifact.created_by_job_id == job_id)
                .order_by(Artifact.created_at)
            ).all()
            if not artifacts:
                return
            excerpts = []
            for artifact in artifacts[:3]:
                path = settings.data_dir / artifact.path
                if artifact.format in ("markdown", "json", "text") and path.is_file():
                    excerpts.append(
                        f"[{artifact.type}: {artifact.title}]\n"
                        + path.read_text(encoding="utf-8")[:2500]
                    )
            pages = db.scalars(select(WikiPage).where(WikiPage.project_id == project_id)).all()
            current = [
                {"slug": p.slug, "title": p.title, "content_md": p.content_md} for p in pages
            ]
            summary = f"Job {job.kind} completado con {len(artifacts)} artefactos"

        client = _client(job_id, agent="librarian", work_unit_key="memory")
        updates = run_librarian(
            client, settings.openrouter_model, current, summary, "\n\n".join(excerpts)
        )
        if not updates:
            return
        with SessionLocal() as db:
            for update in updates:
                page = db.scalars(
                    select(WikiPage).where(
                        WikiPage.project_id == project_id, WikiPage.slug == update.slug
                    )
                ).first()
                if page is None:
                    db.add(
                        WikiPage(
                            project_id=project_id,
                            slug=update.slug,
                            title=update.title,
                            content_md=update.content_md,
                        )
                    )
                else:
                    page.title = update.title
                    page.content_md = update.content_md
            db.commit()
        append_event(
            job_id,
            "memory",
            "Memoria del proyecto actualizada: " + ", ".join(u.slug for u in updates),
        )
    except Exception:
        logger.exception("Memory consolidation failed for job %s", job_id)


def extract_srt_timestamps(srt_content: str) -> list[str]:
    """Start times ('MM:SS') of each SRT entry, for video chapters."""
    stamps = []
    for line in srt_content.splitlines():
        if " --> " in line:
            start = line.split(" --> ")[0].strip()  # HH:MM:SS,mmm
            h, m, s = start.split(",")[0].split(":")
            stamps.append(f"{m}:{s}" if h == "00" else f"{h}:{m}:{s}")
    return stamps


def run_publisher_job(job_id: str, payload: dict) -> dict:
    from factory_agents.agents.publisher import render_publisher_input, run_publisher
    from factory_agents.tools.thumbnail import render_thumbnail

    settings = get_settings()
    videos = _latest_by_base(payload["project_id"], "video")
    if not videos:
        raise RuntimeError("Falta el artefacto 'video': ejecuta antes el montaje de vídeo")
    subtitles = _latest_by_base(payload["project_id"], "subtitles")
    scripts = _latest_by_base(payload["project_id"], "teaching_script")
    client = _client(
        job_id,
        agent="publisher",
        work_unit_key="publisher",
        workflow_step=payload.get("_workflow_step"),
    )
    language = payload.get("project", {}).get("language", "es")

    artifact_ids: list[str] = []
    thumbnail_ids: list[str] = []
    for base, video in videos.items():
        unit, cached = _before_unit(
            job_id,
            payload,
            "publisher",
            video.id,
            f"Preparando la publicación de {base}",
        )
        if cached and cached.get("artifact_id"):
            artifact_ids.append(cached["artifact_id"])
            if cached.get("thumbnail_id"):
                thumbnail_ids.append(cached["thumbnail_id"])
            continue
        append_event(job_id, "stage", f"Preparando publicación de {base}…")
        srt_artifact = subtitles.get(base)
        chapters = []
        if srt_artifact is not None:
            srt_path = settings.data_dir / srt_artifact.path
            if srt_path.is_file():
                chapters = extract_srt_timestamps(srt_path.read_text(encoding="utf-8"))
        script_artifact = scripts.get(base)
        script_md = ""
        if script_artifact is not None:
            script_md = (settings.data_dir / script_artifact.path).read_text(encoding="utf-8")
        package = run_publisher(
            _augment_input(
                render_publisher_input(
                    base, payload.get("project_title", ""), chapters, script_md, language
                ),
                payload,
            ),
            client=client,
            model=payload.get("model") or settings.openrouter_model,
            soul_md=payload.get("soul_md", ""),
            agents_md=payload.get("agents_md", ""),
        )
        package_id = _save_artifact(
            job_id,
            payload["project_id"],
            "publication_package",
            f"Publicación — {base}",
            package.model_dump_json(indent=2),
            format_="json",
        )
        artifact_ids.append(package_id)

        workdir = settings.data_dir / "runs" / job_id
        thumb = render_thumbnail(
            package.thumbnail_title or package.video_title,
            package.thumbnail_subtitle,
            payload.get("project_title", "Curso"),
            workdir / f"thumb-{len(artifact_ids)}.png",
        )
        if thumb is not None:
            thumb_id = _register_artifact_file(
                job_id, payload["project_id"], "thumbnail", f"Miniatura — {base}", thumb, "image"
            )
            thumbnail_ids.append(thumb_id)
            append_event(
                job_id, "artifact", f"Miniatura de {base} lista", {"artifact_id": thumb_id}
            )
        else:
            append_event(
                job_id, "stage", "Chromium no disponible: miniatura omitida (solo metadatos)"
            )
        append_event(
            job_id,
            "artifact",
            f"Paquete de publicación de {base} listo",
            {"artifact_id": package_id},
        )
        _complete_unit(
            job_id,
            "publisher",
            unit,
            {
                "artifact_id": package_id,
                "thumbnail_id": thumbnail_ids[-1] if thumb is not None else None,
            },
            message=f"Publicación de {base} completada",
        )
    _deactivate_unproduced(payload["project_id"], "publication_package", artifact_ids)
    _deactivate_unproduced(payload["project_id"], "thumbnail", thumbnail_ids)
    return {"artifact_ids": artifact_ids}


def run_youtube_upload_job(job_id: str, payload: dict) -> dict:
    """Upload a video to YouTube. Only reachable via explicit user action."""
    import json as _json

    from factory_api.models import OAuthToken
    from factory_api.youtube import upload_video

    settings = get_settings()
    with SessionLocal() as db:
        token = db.scalars(
            select(OAuthToken).where(OAuthToken.provider == "google").limit(1)
        ).first()
        if token is None:
            raise RuntimeError("YouTube no está conectado: autoriza el acceso primero")
        token_data = _json.loads(token.token_json)
        video = db.get(Artifact, payload["video_artifact_id"])
        package_artifact = db.get(Artifact, payload["package_artifact_id"])
        if video is None or package_artifact is None:
            raise RuntimeError("Artefactos de vídeo o publicación no encontrados")
        video_path = settings.data_dir / video.path
        package = _json.loads(
            (settings.data_dir / package_artifact.path).read_text(encoding="utf-8")
        )
        thumbnails = _latest_by_base(payload["project_id"], "thumbnail")
        base = video.title.removeprefix(PREFIXES["video"])
        thumb = thumbnails.get(base)
        thumb_path = settings.data_dir / thumb.path if thumb else None

    append_event(job_id, "stage", f"Subiendo «{package.get('video_title', '')}» a YouTube…")
    result = upload_video(
        token_data,
        settings.google_client_id,
        settings.google_client_secret,
        str(video_path),
        package,
        privacy=payload.get("privacy", "private"),
        thumbnail_path=str(thumb_path) if thumb_path and thumb_path.is_file() else None,
    )
    append_event(
        job_id,
        "artifact",
        f"Vídeo publicado: {result['url']} (privacidad: {payload.get('privacy', 'private')})",
        result,
    )
    return result


AGENT_OUTPUT_TYPE = {
    "curator": "research_brief",
    "planner": "course_plan",
    "lessons": "lesson_content",
    "slides": "slide_deck",
    "script": "teaching_script",
}


def _run_automatic_review(
    job_id: str,
    agent: str,
    handler,
    payload: dict,
    initial_result: dict,
) -> tuple[dict, dict | None]:
    """Apply a frozen profile review policy outside declarative workflows."""
    if not payload.get("automatic_review_enabled", False):
        return initial_result, None

    max_regenerations = int(payload.get("max_automatic_regenerations", 0) or 0)
    evaluator_model = payload.get("evaluator_model") or get_settings().openrouter_model
    scope = f"{payload.get('_control_scope', f'direct:{agent}')}:automatic-review"
    state = load_scope_state(job_id, scope)
    result = initial_result
    evaluations = int(state.get("evaluations", 0))
    regenerations = int(state.get("regenerations", 0))
    if isinstance(state.get("summary"), dict):
        return result, state["summary"]
    while True:
        verdict = state.get("pending_verdict")
        feedback = str(state.get("pending_feedback", ""))
        if verdict is None:
            checkpoint(
                job_id,
                "automatic_review",
                current_unit=None,
                next_unit=f"{scope}:evaluation:{evaluations + 1}",
                message=f"Preparando evaluación automática de {agent}",
            )
            append_event(
                job_id,
                "evaluation",
                f"Evaluación automática de {agent} iniciada",
                {
                    "agent": agent,
                    "status": "running",
                    "model": evaluator_model,
                    "evaluation": evaluations + 1,
                },
            )
            try:
                verdict, feedback = evaluate_stage(job_id, agent, result)
            except Exception as exc:
                evaluations += 1
                summary = {
                    "agent": agent,
                    "evaluations": evaluations,
                    "regenerations": regenerations,
                    "final_result": "evaluator_error",
                    "model": evaluator_model,
                }
                save_scope_state(
                    job_id,
                    scope,
                    {
                        "evaluations": evaluations,
                        "regenerations": regenerations,
                        "summary": summary,
                    },
                )
                append_event(
                    job_id,
                    "evaluation",
                    f"La evaluación de {agent} falló; la ejecución continúa",
                    {
                        "agent": agent,
                        "status": "warning",
                        "technical_error": True,
                        "error": str(exc),
                        "model": evaluator_model,
                    },
                )
                checkpoint(
                    job_id,
                    "automatic_review",
                    current_unit=f"{scope}:evaluation:{evaluations}",
                    next_unit=None,
                    message=f"Evaluación automática de {agent} finalizada con advertencia",
                )
                return result, summary
            evaluations += 1
            state = {
                "evaluations": evaluations,
                "regenerations": regenerations,
                "pending_verdict": verdict,
                "pending_feedback": feedback,
            }
            save_scope_state(job_id, scope, state)
            checkpoint(
                job_id,
                "automatic_review",
                current_unit=f"{scope}:evaluation:{evaluations}",
                next_unit=(
                    f"{scope}:regeneration:{regenerations + 1}"
                    if verdict != "pass" and regenerations < max_regenerations
                    else None
                ),
                message=f"Evaluación automática {evaluations} de {agent} completada",
            )
        if verdict == "pass":
            summary = {
                "agent": agent,
                "evaluations": evaluations,
                "regenerations": regenerations,
                "final_result": "pass",
                "model": evaluator_model,
            }
            save_scope_state(job_id, scope, {**state, "summary": summary})
            return result, summary
        if regenerations >= max_regenerations:
            destination = (
                "human_approval"
                if payload.get("human_review_enabled", False)
                else "continue"
            )
            if destination == "continue":
                append_event(
                    job_id,
                    "evaluation",
                    f"{agent} agotó {max_regenerations} regeneraciones; "
                    "la ejecución continúa con advertencia",
                    {
                        "agent": agent,
                        "status": "warning",
                        "verdict": verdict,
                        "feedback": feedback,
                        "destination": destination,
                    },
                )
            summary = {
                "agent": agent,
                "evaluations": evaluations,
                "regenerations": regenerations,
                "final_result": "exhausted",
                "destination": destination,
                "feedback": feedback,
                "model": evaluator_model,
            }
            save_scope_state(job_id, scope, {**state, "summary": summary})
            return result, summary
        next_regeneration = regenerations + 1
        checkpoint(
            job_id,
            "automatic_review",
            current_unit=f"{scope}:evaluation:{evaluations}",
            next_unit=f"{scope}:regeneration:{next_regeneration}",
            message=f"Preparando regeneración de {agent}",
        )
        append_event(
            job_id,
            "evaluation",
            f"Regeneración {next_regeneration}/{max_regenerations} de {agent} "
            "con feedback del evaluador…",
            {
                "agent": agent,
                "status": "regenerating",
                "regeneration": next_regeneration,
                "max_regenerations": max_regenerations,
                "feedback": feedback,
            },
        )
        result = handler(
            job_id,
            {
                **payload,
                "revision_feedback": feedback,
                "_control_scope": f"{scope}:regeneration:{next_regeneration}",
            },
        )
        regenerations = next_regeneration
        state = {
            "evaluations": evaluations,
            "regenerations": regenerations,
        }
        save_scope_state(job_id, scope, state)
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.result_json = json.dumps(result, ensure_ascii=False)
                db.commit()
        checkpoint(
            job_id,
            "automatic_review",
            current_unit=f"{scope}:regeneration:{regenerations}",
            next_unit=f"{scope}:evaluation:{evaluations + 1}",
            message=f"Regeneración {regenerations} de {agent} completada",
        )


def evaluate_stage(job_id: str, agent: str, result: dict | None) -> tuple[str, str]:
    """Judge a stage's artifacts. Returns (verdict, feedback)."""
    from factory_agents.evals import run_evaluator

    settings = get_settings()
    artifact_type = AGENT_OUTPUT_TYPE.get(agent)
    if artifact_type is None or not result:
        append_event(
            job_id,
            "evaluation",
            f"Evaluación de {agent} omitida: no hay una rúbrica aplicable",
            {
                "agent": agent,
                "status": "done",
                "verdict": "pass",
                "skipped": True,
                "model": settings.openrouter_model,
            },
        )
        return "pass", ""
    ids = result.get("artifact_ids") or (
        [result["artifact_id"]] if result.get("artifact_id") else []
    )
    excerpts = []
    with SessionLocal() as db:
        for artifact_id in ids[:2]:
            artifact = db.get(Artifact, artifact_id)
            if artifact is None:
                continue
            path = settings.data_dir / artifact.path
            if path.is_file():
                excerpts.append(f"[{artifact.title}]\n" + path.read_text(encoding="utf-8"))
    if not excerpts:
        append_event(
            job_id,
            "evaluation",
            f"Evaluación de {agent} omitida: no hay contenido legible",
            {
                "agent": agent,
                "status": "done",
                "verdict": "pass",
                "skipped": True,
                "model": settings.openrouter_model,
            },
        )
        return "pass", ""
    evaluation = run_evaluator(
        _client(
            job_id,
            agent=agent,
            operation="evaluator",
            work_unit_key=f"{agent}:evaluation",
            workflow_step=_CURRENT_WORKFLOW_STEP.get(),
        ),
        settings.openrouter_model,
        artifact_type,
        "\n\n---\n\n".join(excerpts),
    )
    icon = "✔" if evaluation.verdict == "pass" else "✎"
    append_event(
        job_id,
        "evaluation",
        f"{icon} Evaluación de {agent}: {evaluation.verdict} (nota {evaluation.score}/10)"
        + (f" — {evaluation.feedback}" if evaluation.feedback else ""),
        {
            "agent": agent,
            "status": "done",
            "verdict": evaluation.verdict,
            "score": evaluation.score,
            "model": settings.openrouter_model,
        },
    )
    if ids:
        with SessionLocal() as db:
            evaluated_artifact = db.get(Artifact, ids[0])
            if evaluated_artifact is not None:
                attach_usage_to_artifact(
                    db,
                    evaluated_artifact,
                    job_id=job_id,
                    agent=agent,
                    operation="evaluator",
                )
                db.commit()
    return evaluation.verdict, evaluation.feedback


def run_analyst_job(job_id: str, payload: dict) -> dict:
    """Continuous-improvement analysis for one project's published videos."""
    import json as _json

    from factory_agents.agents.analyst import render_analyst_input, run_analyst

    from factory_api.models import ImprovementProposal, OAuthToken, WikiPage
    from factory_api.youtube import fetch_videos_data

    settings = get_settings()
    project_id = payload["project_id"]

    # Videos uploaded for this project (from completed upload jobs).
    with SessionLocal() as db:
        upload_jobs = db.scalars(
            select(Job).where(
                Job.project_id == project_id,
                Job.kind == "youtube_upload",
                Job.status == "done",
            )
        ).all()
        video_ids = []
        for upload_job in upload_jobs:
            result = _json.loads(upload_job.result_json or "{}")
            if result.get("video_id"):
                video_ids.append(result["video_id"])
        token = db.scalars(
            select(OAuthToken).where(OAuthToken.provider == "google").limit(1)
        ).first()
        token_data = _json.loads(token.token_json) if token else None

    if not video_ids:
        raise RuntimeError(
            "Este proyecto no tiene vídeos publicados en YouTube todavía: "
            "publica al menos uno para poder analizar su rendimiento"
        )
    if token_data is None:
        raise RuntimeError("YouTube no está conectado: autoriza el acceso primero")

    append_event(job_id, "stage", f"Recogiendo métricas de {len(video_ids)} vídeo(s)…")
    videos_data = fetch_videos_data(
        token_data, settings.google_client_id, settings.google_client_secret, video_ids
    )
    total_comments = sum(len(v.get("comments", [])) for v in videos_data)
    append_event(job_id, "stage", f"Datos recogidos ({total_comments} comentarios). Analizando…")

    with SessionLocal() as db:
        # Current default agents.md per agent, so proposals are minimal diffs.
        from factory_api.routers.agents import get_default_profile

        current_agents_md = {}
        for agent in ("curator", "planner", "lessons", "slides", "script", "voice", "publisher"):
            profile = get_default_profile(db, agent)
            if profile is not None:
                current_agents_md[agent] = profile.agents_md
        channel_wiki = [
            {"slug": p.slug, "title": p.title, "content_md": p.content_md}
            for p in db.scalars(select(WikiPage).where(WikiPage.project_id.is_(None))).all()
        ]

    result = run_analyst(
        render_analyst_input(
            payload.get("project_title", ""),
            videos_data,
            current_agents_md,
            channel_wiki,
        ),
        client=_client(job_id, agent="analyst", work_unit_key="analyst"),
        model=payload.get("model") or settings.openrouter_model,
        soul_md=payload.get("soul_md", ""),
        agents_md=payload.get("agents_md", ""),
    )

    report_id = _save_artifact(
        job_id,
        project_id,
        "performance_report",
        f"Informe de rendimiento — {payload.get('project_title', '')}".strip(" —"),
        result.report_md,
    )
    append_event(job_id, "artifact", "Informe de rendimiento generado", {"artifact_id": report_id})

    proposal_ids = []
    with SessionLocal() as db:
        for draft in result.proposals:
            proposal = ImprovementProposal(
                project_id=project_id,
                kind=draft.kind,
                agent_type=draft.agent_type,
                slug=draft.slug or "canal-aprendizajes",
                title=draft.title,
                proposed_content=draft.proposed_content,
                evidence=draft.evidence,
                created_by_job_id=job_id,
            )
            db.add(proposal)
            db.flush()
            proposal_ids.append(proposal.id)
        db.commit()
    if proposal_ids:
        append_event(
            job_id,
            "stage",
            f"{len(proposal_ids)} propuesta(s) de mejora pendientes de tu revisión "
            f"(ninguna se aplica sola)",
        )
    return {"artifact_id": report_id, "proposal_ids": proposal_ids}


def run_workflow_job(job_id: str, payload: dict) -> dict:
    """Execute (or resume) a declarative workflow via LangGraph."""
    from langgraph.types import Command

    from factory_api.workflow_engine import build_workflow_graph, open_checkpointer

    definition = payload["definition"]
    def evaluate_workflow_stage(agent: str, result: dict, step: int):
        token = _CURRENT_WORKFLOW_STEP.set(step)
        try:
            return evaluate_stage(job_id, agent, result)
        finally:
            _CURRENT_WORKFLOW_STEP.reset(token)

    graph = build_workflow_graph(
        definition,
        job_id,
        HANDLERS,
        append_event,
        evaluator=evaluate_workflow_stage,
    )
    with open_checkpointer() as checkpointer:
        compiled = graph.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": job_id}}
        existing_state = compiled.get_state(config)
        resume_decision = payload.get("_resume")
        if resume_decision is not None:
            graph_input = Command(resume=resume_decision)
        elif existing_state.values:
            graph_input = None
        else:
            graph_input = {
                "payload": payload,
                "results": {},
                "review_summaries": {},
                "human_reviews": {},
                "human_actions": {},
            }
        resume_cleared = resume_decision is None
        for update in compiled.stream(graph_input, config, stream_mode="updates"):
            if not resume_cleared:
                with SessionLocal() as db:
                    job = db.get(Job, job_id)
                    if job is not None:
                        stored_payload = json.loads(job.payload_json or "{}")
                        stored_payload.pop("_resume", None)
                        job.payload_json = json.dumps(
                            stored_payload, ensure_ascii=False
                        )
                        db.commit()
                resume_cleared = True
            if "__interrupt__" in update:
                intr = update["__interrupt__"][0]
                value = intr.value if isinstance(intr.value, dict) else {}
                append_event(
                    job_id,
                    "approval_required",
                    f"Aprobación requerida tras el paso {value.get('step', '?')} "
                    f"({value.get('agent', '?')})",
                    value,
                )
                return {"__waiting__": True}
        if not resume_cleared:
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if job is not None:
                    stored_payload = json.loads(job.payload_json or "{}")
                    stored_payload.pop("_resume", None)
                    job.payload_json = json.dumps(stored_payload, ensure_ascii=False)
                    db.commit()
        state = compiled.get_state(config)
        results = dict(state.values.get("results", {}))
        review_summaries = dict(state.values.get("review_summaries", {}))
        if review_summaries:
            results["_automatic_reviews"] = review_summaries
        human_reviews = dict(state.values.get("human_reviews", {}))
        if human_reviews:
            results["_human_reviews"] = human_reviews
        return results


HANDLERS = {
    "curator_run": run_curator_job,
    "planner_run": run_planner_job,
    "lessons_run": run_lessons_job,
    "slides_run": run_slides_job,
    "script_run": run_script_job,
    "voice_run": run_voice_job,
    "video_run": run_video_job,
    "publisher_run": run_publisher_job,
    "youtube_upload": run_youtube_upload_job,
    "analyst_run": run_analyst_job,
    "pipeline_run": run_pipeline_job,
    "workflow_run": run_workflow_job,
}

# Jobs whose output feeds the project memory (librarian pass after success).
MEMORY_KINDS = {
    "curator_run",
    "planner_run",
    "lessons_run",
    "slides_run",
    "script_run",
    "publisher_run",
    "pipeline_run",
    "workflow_run",
}

runner = JobRunner()
