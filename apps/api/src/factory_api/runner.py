"""In-process task runner.

Jobs are persisted in SQLite (they survive restarts: queued jobs are
re-enqueued on boot) and executed one at a time by an asyncio worker.
Agent work runs in a thread (deep agents are sync) and reports progress
by appending JobEvents, which the SSE endpoint streams to the UI.
"""

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from factory_api.artifact_versions import (
    add_artifact_version,
    artifact_logical_key,
    artifact_metadata,
    selected_artifact,
)
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
            pending = db.scalars(select(Job.id).where(Job.status.in_(["queued", "running"]))).all()
        for job_id in pending:
            self._queue.put_nowait(job_id)
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
        logger.info("Job runner stopped")

    def enqueue(self, job_id: str) -> None:
        # If the runner is not started the job stays queued in the DB and is
        # picked up on the next start().
        if self._queue is not None:
            self._queue.put_nowait(job_id)
            logger.info("Job enqueued", extra={"job_id": job_id})

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
            logger.info(
                "Job execution started",
                extra={
                    "job_id": job_id,
                    "job_kind": kind,
                    "project_id": job.project_id,
                },
            )
        _TOKENS_USED.setdefault(job_id, 0)

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
            else:
                effective_payload = dict(payload)
                if direct_agent is not None and resume.get("approved") is False:
                    effective_payload["revision_feedback"] = resume.get("feedback", "")
                result = handler(job_id, effective_payload)
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
            if isinstance(result, dict) and result.get("__waiting__"):
                self._set_waiting(job_id)
            else:
                if kind in MEMORY_KINDS:
                    consolidate_memory(job_id)
                self._finish(job_id, result=result)
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            self._finish(job_id, error=str(exc))

    def _set_waiting(
        self,
        job_id: str,
        payload: dict | None = None,
        result: dict | None = None,
    ) -> None:
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
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job is None:
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


def add_tokens(job_id: str, tokens: int) -> None:
    settings = get_settings()
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
    """Wraps the OpenAI-compatible client to enforce the per-run budget."""

    def __init__(self, inner, job_id: str):
        self._inner = inner
        self._job_id = job_id
        self.chat = type(
            "chat", (), {"completions": type("completions", (), {"create": self._create})()}
        )()

    def _create(self, **kwargs):
        response = self._inner.chat.completions.create(**kwargs)
        usage = getattr(response, "usage", None)
        if usage is not None:
            add_tokens(
                self._job_id,
                (getattr(usage, "prompt_tokens", 0) or 0)
                + (getattr(usage, "completion_tokens", 0) or 0),
            )
        return response


def _client(job_id: str):
    from factory_agents.llm import get_llm_client

    settings = get_settings()
    return TrackedClient(get_llm_client(settings.openrouter_api_key), job_id)


def _budget_callbacks(job_id: str) -> list:
    """LangChain callback tracking deep-agent token usage against the budget."""
    from langchain_core.callbacks import BaseCallbackHandler

    class BudgetCallback(BaseCallbackHandler):
        raise_error = True

        def on_llm_end(self, response, **kwargs):
            for generations in response.generations:
                for generation in generations:
                    message = getattr(generation, "message", None)
                    usage = getattr(message, "usage_metadata", None) or {}
                    add_tokens(
                        job_id,
                        (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0),
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
        artifact = add_artifact_version(
            db,
            project_id=project_id,
            type_=type_,
            format_=format_,
            title=title,
            path=rel_path,
            created_by_job_id=job_id,
            metadata=metadata,
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
    final_text = ""
    for event in run_curator(
        _augment_input(payload["task_input"], payload),
        model=payload.get("model") or settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        tavily_api_key=settings.tavily_api_key,
        workspace_dir=str(workspace),
        soul_md=payload.get("soul_md", ""),
        agents_md=payload.get("agents_md", ""),
        recursion_limit=settings.agent_recursion_limit,
        callbacks=_budget_callbacks(job_id),
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


def run_planner_job(job_id: str, payload: dict) -> dict:
    from factory_agents.agents.planner import render_planner_input, run_planner

    settings = get_settings()
    brief_md = _require_artifact(
        payload["project_id"], "research_brief", "ejecuta antes el Curador"
    )
    append_event(job_id, "stage", "Diseñando la estructura del curso…")
    plan = run_planner(
        _augment_input(render_planner_input(payload.get("project", {}), brief_md), payload),
        client=_client(job_id),
        model=payload.get("model") or settings.openrouter_model,
        soul_md=payload.get("soul_md", ""),
        agents_md=payload.get("agents_md", ""),
    )
    artifact_id = _save_artifact(
        job_id,
        payload["project_id"],
        "course_plan",
        f"Plan del curso — {plan.course_title}",
        plan.model_dump_json(indent=2),
        format_="json",
    )
    total = sum(len(m.lessons) for m in plan.modules)
    append_event(
        job_id,
        "artifact",
        f"Plan generado: {len(plan.modules)} módulos, {total} lecciones",
        {"artifact_id": artifact_id},
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

    artifact_ids: list[str] = []
    for mi, li, _module, lesson in plan.iter_lessons():
        label = f"{mi}.{li} {lesson.title}"
        append_event(job_id, "stage", f"Escribiendo lección {label}…")
        final_text = ""
        for event in run_lesson(
            _augment_input(render_lesson_input(plan, mi, li, brief_md), payload),
            model=payload.get("model") or settings.openrouter_model,
            api_key=settings.openrouter_api_key,
            workspace_dir=str(settings.data_dir / "runs" / job_id / f"lesson-{mi}-{li}"),
            soul_md=payload.get("soul_md", ""),
            agents_md=payload.get("agents_md", ""),
            recursion_limit=settings.agent_recursion_limit,
            callbacks=_budget_callbacks(job_id),
        ):
            if event.type == "result":
                final_text = event.summary
            elif event.type == "tool_call":
                append_event(job_id, event.type, f"[{label}] {event.summary}", event.data)
        if not final_text.strip():
            raise RuntimeError(f"La lección {label} quedó vacía")
        artifact_id = _save_artifact(
            job_id, payload["project_id"], "lesson_content", label, final_text
        )
        artifact_ids.append(artifact_id)
        append_event(job_id, "artifact", f"Lección {label} lista", {"artifact_id": artifact_id})

    _deactivate_unproduced(payload["project_id"], "lesson_content", artifact_ids)
    return {"artifact_ids": artifact_ids}


def run_slides_job(job_id: str, payload: dict) -> dict:
    from factory_agents.agents.slides import render_slides_input, run_slides
    from factory_agents.contracts import CoursePlan
    from factory_agents.tools.images import generate_deck_images, parse_image_slots
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
    client = _client(job_id)

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
    for title, (_lesson_id, rel_path) in by_title.items():
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
            ),
            client=client,
            model=payload.get("model") or settings.openrouter_model,
            soul_md=payload.get("soul_md", ""),
            agents_md=payload.get("agents_md", ""),
            orientation=orientation,
            images_enabled=images_enabled,
        )
        deck = apply_slide_palette(deck, slide_palette)
        image_records: list[dict] = []
        if images_enabled:
            slots = parse_image_slots(deck)
            if not slots:
                append_event(
                    job_id,
                    "warning",
                    f"El agente no seleccionó imágenes para {title}",
                    {"lesson": title},
                )
            asset_dir_name = f"slide-assets-{job_id}-{uuid.uuid4().hex[:8]}"
            storage_asset_dir = f"artifacts/{payload['project_id']}/{asset_dir_name}"
            deck, image_records = generate_deck_images(
                deck,
                api_key=settings.openrouter_api_key,
                model=image_model,
                style=image_style,
                custom_style_prompt=image_style_prompt,
                orientation=orientation,
                deck_identity=f"{plan.course_title}:{title}",
                output_dir=settings.data_dir / storage_asset_dir,
                markdown_asset_dir=asset_dir_name,
                storage_asset_dir=storage_asset_dir,
                on_event=lambda event_type, summary, data, lesson_title=title: append_event(
                    job_id, event_type, f"[{lesson_title}] {summary}", data
                ),
            )
        generation_cost = sum(
            float(item["cost_usd"])
            for item in image_records
            if item.get("cost_usd") is not None
        )
        artifact_id = _save_artifact(
            job_id,
            payload["project_id"],
            "slide_deck",
            f"Slides — {title}",
            deck,
            metadata={
                "orientation": orientation,
                "width": width,
                "height": height,
                "slide_palette": slide_palette,
                "palette_name": palette_name,
                "palette_contrast": palette_contrast(slide_palette),
                "palette_warnings": contrast_warnings,
                "images": image_records,
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
        with SessionLocal() as db:
            artifact = db.get(Artifact, artifact_id)
            deck_path = settings.data_dir / artifact.path
        rendered = render_deck(deck_path)
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
        artifact = add_artifact_version(
            db,
            project_id=project_id,
            type_=type_,
            format_=format_,
            title=title,
            path=rel_path,
            created_by_job_id=job_id,
            metadata=metadata,
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
    client = _client(job_id)

    artifact_ids: list[str] = []
    for base, deck in decks.items():
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
            ),
            client=client,
            model=payload.get("model") or settings.openrouter_model,
            soul_md=payload.get("soul_md", ""),
            agents_md=payload.get("agents_md", ""),
        )
        artifact_id = _save_artifact(
            job_id, payload["project_id"], "teaching_script", f"Guion — {base}", script_md
        )
        artifact_ids.append(artifact_id)
        append_event(job_id, "artifact", f"Guion de {base} listo", {"artifact_id": artifact_id})
    _deactivate_unproduced(payload["project_id"], "teaching_script", artifact_ids)
    return {"artifact_ids": artifact_ids}


def run_voice_job(job_id: str, payload: dict) -> dict:
    from factory_agents.agents.voice import render_voice_input, run_voice

    settings = get_settings()
    scripts = _latest_by_base(payload["project_id"], "teaching_script")
    if not scripts:
        raise RuntimeError(
            "Falta el artefacto 'teaching_script': ejecuta antes el Guionista docente"
        )
    client = _client(job_id)
    language = payload.get("project", {}).get("language", "es")

    artifact_ids: list[str] = []
    for base, script in scripts.items():
        append_event(job_id, "stage", f"Adaptando a voz {base}…")
        script_md = (settings.data_dir / script.path).read_text(encoding="utf-8")
        voice_script = run_voice(
            render_voice_input(script_md, base, language),
            client=client,
            model=payload.get("model") or settings.openrouter_model,
            soul_md=payload.get("soul_md", ""),
            agents_md=payload.get("agents_md", ""),
        )
        artifact_id = _save_artifact(
            job_id,
            payload["project_id"],
            "voice_script",
            f"Voz — {base}",
            voice_script.model_dump_json(indent=2),
            format_="json",
        )
        artifact_ids.append(artifact_id)
        append_event(
            job_id,
            "artifact",
            f"Guion de voz de {base} listo ({len(voice_script.segments)} segmentos)",
            {"artifact_id": artifact_id},
        )
    _deactivate_unproduced(payload["project_id"], "voice_script", artifact_ids)
    return {"artifact_ids": artifact_ids}


def run_video_job(job_id: str, payload: dict) -> dict:
    from factory_agents.contracts import VoiceScript
    from factory_agents.tools.tts import OpenAITTSProvider, synthesize_cached
    from factory_agents.tools.video import (
        build_srt,
        compose_video,
        probe_duration,
        render_slide_images,
    )

    settings = get_settings()
    voices = _latest_by_base(payload["project_id"], "voice_script")
    decks = _latest_by_base(payload["project_id"], "slide_deck")
    if not voices:
        raise RuntimeError("Falta el artefacto 'voice_script': ejecuta antes el Adaptador de voz")

    provider = OpenAITTSProvider(
        settings.openai_api_key, voice=settings.tts_voice, model=settings.tts_model
    )
    cache_dir = settings.data_dir / "tts-cache"
    workdir_root = settings.data_dir / "runs" / job_id
    orientation = payload.get("orientation", "horizontal")
    width, height = ((1080, 1920) if orientation == "vertical" else (1920, 1080))

    video_ids: list[str] = []
    subtitle_ids: list[str] = []
    for base, voice_artifact in voices.items():
        deck = decks.get(base)
        if deck is None:
            raise RuntimeError(f"No hay slide_deck para «{base}»: regenera las slides")
        workdir = workdir_root / base.replace("/", "_").replace(" ", "_")[:60]

        append_event(job_id, "stage", f"Renderizando slides de {base} a imágenes…")
        images = render_slide_images(settings.data_dir / deck.path, workdir / "slides")

        voice_script = VoiceScript.model_validate_json(
            (settings.data_dir / voice_artifact.path).read_text(encoding="utf-8")
        )
        append_event(
            job_id,
            "stage",
            f"Sintetizando narración de {base} ({len(voice_script.segments)} segmentos)…",
        )
        pairs: list[tuple] = []
        srt_segments: list[tuple[str, float]] = []
        for segment in voice_script.segments:
            audio = synthesize_cached(provider, segment.text, cache_dir)
            image = images[min(segment.slide, len(images)) - 1]
            pairs.append((image, audio))
            srt_segments.append((segment.text, probe_duration(audio)))

        append_event(
            job_id,
            "stage",
            f"Montando vídeo {orientation} de {base} (ffmpeg)…",
        )
        out_mp4 = workdir / "lesson.mp4"
        compose_video(pairs, out_mp4, workdir / "segments", orientation=orientation)

        video_id = _register_artifact_file(
            job_id,
            payload["project_id"],
            "video",
            f"Vídeo — {base}",
            out_mp4,
            "video",
            metadata={
                "orientation": orientation,
                "width": width,
                "height": height,
                "slide_orientation": artifact_metadata(deck).get(
                    "orientation", "horizontal"
                ),
                "slide_deck_id": deck.id,
                "voice_script_id": voice_artifact.id,
            },
        )
        srt_id = _save_artifact_if_changed(
            job_id,
            payload["project_id"],
            "subtitles",
            f"Subtítulos — {base}",
            build_srt(srt_segments),
            format_="text",
            metadata={"voice_script_id": voice_artifact.id},
        )
        video_ids.append(video_id)
        subtitle_ids.append(srt_id)
        duration = sum(d for _t, d in srt_segments)
        append_event(
            job_id,
            "artifact",
            f"Vídeo {orientation} de {base} listo ({duration / 60:.1f} min)",
            {
                "artifact_id": video_id,
                "subtitles_id": srt_id,
                "orientation": orientation,
            },
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


def _augment_input(task_input: str, payload: dict) -> str:
    """Attach wiki memory and (when revising) the evaluator feedback."""
    parts = [_with_wiki(task_input, payload["project_id"])]
    feedback = payload.get("revision_feedback")
    if feedback:
        parts.append(
            "# Feedback del evaluador (versión anterior rechazada — corrige esto)\n\n" + feedback
        )
    return "\n\n".join(parts)


def consolidate_memory(job_id: str) -> None:
    """Librarian pass after a successful job (best-effort, never raises)."""
    from factory_agents.llm import get_llm_client
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

        client = get_llm_client(settings.openrouter_api_key)
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
    client = _client(job_id)
    language = payload.get("project", {}).get("language", "es")

    artifact_ids: list[str] = []
    thumbnail_ids: list[str] = []
    for base, _video in videos.items():
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
    result = initial_result
    evaluations = 0
    regenerations = 0
    while True:
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
            return result, {
                "agent": agent,
                "evaluations": evaluations + 1,
                "regenerations": regenerations,
                "final_result": "evaluator_error",
                "model": evaluator_model,
            }
        evaluations += 1
        if verdict == "pass":
            return result, {
                "agent": agent,
                "evaluations": evaluations,
                "regenerations": regenerations,
                "final_result": "pass",
                "model": evaluator_model,
            }
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
            return result, {
                "agent": agent,
                "evaluations": evaluations,
                "regenerations": regenerations,
                "final_result": "exhausted",
                "destination": destination,
                "feedback": feedback,
                "model": evaluator_model,
            }
        regenerations += 1
        append_event(
            job_id,
            "evaluation",
            f"Regeneración {regenerations}/{max_regenerations} de {agent} "
            "con feedback del evaluador…",
            {
                "agent": agent,
                "status": "regenerating",
                "regeneration": regenerations,
                "max_regenerations": max_regenerations,
                "feedback": feedback,
            },
        )
        result = handler(job_id, {**payload, "revision_feedback": feedback})


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
        _client(job_id),
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
        client=_client(job_id),
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
    graph = build_workflow_graph(
        definition,
        job_id,
        HANDLERS,
        append_event,
        evaluator=lambda agent, result: evaluate_stage(job_id, agent, result),
    )
    with open_checkpointer() as checkpointer:
        compiled = graph.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": job_id}}
        if payload.get("_resume") is not None:
            graph_input = Command(resume=payload["_resume"])
        else:
            graph_input = {
                "payload": payload,
                "results": {},
                "review_summaries": {},
                "human_reviews": {},
                "human_actions": {},
            }
        for update in compiled.stream(graph_input, config, stream_mode="updates"):
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
