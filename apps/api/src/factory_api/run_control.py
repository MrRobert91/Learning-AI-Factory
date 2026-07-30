"""Persistent cooperative pause, resume and cancellation for jobs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from factory_api.db import SessionLocal
from factory_api.models import Job

TERMINAL_STATUSES = {"done", "failed", "canceled"}
SSE_STOP_STATUSES = TERMINAL_STATUSES | {"paused", "waiting_approval"}


class InvalidControlTransition(ValueError):
    def __init__(self, status: str, action: str):
        super().__init__(f"No se puede {action} una ejecución en estado '{status}'")
        self.status = status
        self.action = action


class RunPaused(RuntimeError):
    def __init__(self, checkpoint: dict[str, Any]):
        super().__init__("Ejecución pausada")
        self.checkpoint = checkpoint


class RunCanceled(RuntimeError):
    def __init__(self, checkpoint: dict[str, Any]):
        super().__init__("Ejecución cancelada")
        self.checkpoint = checkpoint


def utcnow() -> datetime:
    return datetime.now(UTC)


def _iso_now() -> str:
    return utcnow().isoformat()


def load_control(job: Job) -> dict[str, Any]:
    try:
        value = json.loads(job.control_json or "{}")
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def store_control(job: Job, control: dict[str, Any]) -> None:
    job.control_json = json.dumps(control, ensure_ascii=False)


def request_pause(job: Job, reason: str = "") -> bool:
    """Request or immediately apply a pause. Returns whether state changed."""
    control = load_control(job)
    if job.status in {"pausing", "paused"}:
        return False
    if job.status not in {"queued", "running", "waiting_approval"}:
        raise InvalidControlTransition(job.status, "pausar")

    now = _iso_now()
    control.update(
        {
            "pause_requested_at": control.get("pause_requested_at") or now,
            "pause_reason": reason.strip(),
            "paused_from": job.status,
            "last_action": "pause",
        }
    )
    if job.status == "running":
        job.status = "pausing"
    else:
        job.status = "paused"
        control["paused_at"] = now
    store_control(job, control)
    return True


def resume_job(job: Job) -> tuple[bool, bool]:
    """Resume a paused job. Returns (state_changed, should_enqueue)."""
    control = load_control(job)
    if job.status != "paused":
        if control.get("last_action") == "resume" and job.status in {
            "queued",
            "running",
            "waiting_approval",
        }:
            return False, False
        raise InvalidControlTransition(job.status, "reanudar")

    paused_from = control.get("paused_from")
    job.status = "waiting_approval" if paused_from == "waiting_approval" else "queued"
    job.finished_at = None
    job.error = ""
    control.update(
        {
            "resumed_at": _iso_now(),
            "resume_count": int(control.get("resume_count", 0)) + 1,
            "last_action": "resume",
        }
    )
    store_control(job, control)
    return True, job.status == "queued"


def request_cancel(job: Job, reason: str = "") -> bool:
    """Request cooperative cancellation or cancel an idle job immediately."""
    control = load_control(job)
    if job.status in {"canceling", "canceled"}:
        return False
    if job.status not in {
        "queued",
        "running",
        "pausing",
        "paused",
        "waiting_approval",
    }:
        raise InvalidControlTransition(job.status, "cancelar")

    now = _iso_now()
    control.update(
        {
            "cancel_requested_at": control.get("cancel_requested_at") or now,
            "cancel_reason": reason.strip(),
            "last_action": "cancel",
        }
    )
    if job.status in {"running", "pausing"}:
        job.status = "canceling"
    else:
        job.status = "canceled"
        job.finished_at = utcnow()
        job.error = "Cancelado por el usuario"
        control["canceled_at"] = now
    store_control(job, control)
    return True


def _unit_payload(value: dict[str, Any] | None) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def checkpoint(
    job_id: str,
    phase: str,
    *,
    current_unit: str | None = None,
    next_unit: str | None = None,
    message: str = "",
    completed_unit: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    """Persist a safe point and stop if pause/cancel was requested."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            raise RunCanceled({})
        control = load_control(job)
        completed = control.setdefault("completed_units", {})
        if completed_unit:
            completed[completed_unit] = _unit_payload(result)
        point = {
            "phase": phase,
            "current_unit": current_unit,
            "next_unit": next_unit,
            "message": message,
            "updated_at": _iso_now(),
        }
        if completed_unit:
            point["last_completed_unit"] = completed_unit
        elif isinstance(control.get("checkpoint"), dict):
            previous = control["checkpoint"].get("last_completed_unit")
            if previous:
                point["last_completed_unit"] = previous
        control["checkpoint"] = point

        if job.status in {"canceling", "canceled"}:
            job.status = "canceled"
            job.finished_at = utcnow()
            job.error = "Cancelado por el usuario"
            control["canceled_at"] = control.get("canceled_at") or _iso_now()
            store_control(job, control)
            db.commit()
            raise RunCanceled(point)
        if job.status in {"pausing", "paused"}:
            job.status = "paused"
            control["paused_at"] = control.get("paused_at") or _iso_now()
            control["paused_from"] = control.get("paused_from") or "running"
            store_control(job, control)
            db.commit()
            raise RunPaused(point)

        store_control(job, control)
        db.commit()


def completed_unit(job_id: str, unit: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return None
        completed = load_control(job).get("completed_units", {})
        value = completed.get(unit) if isinstance(completed, dict) else None
        return value if isinstance(value, dict) else None


def is_cancel_requested(job_id: str) -> bool:
    """Lightweight polling hook for bounded external subprocesses."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        return job is None or job.status in {"canceling", "canceled"}


def load_scope_state(job_id: str, scope: str) -> dict[str, Any]:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return {}
        scopes = load_control(job).get("scope_state", {})
        value = scopes.get(scope) if isinstance(scopes, dict) else None
        return value if isinstance(value, dict) else {}


def save_scope_state(job_id: str, scope: str, state: dict[str, Any]) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        control = load_control(job)
        scopes = control.setdefault("scope_state", {})
        scopes[scope] = state
        store_control(job, control)
        db.commit()


def recover_jobs(db: Session) -> tuple[list[str], list[tuple[str, str, dict[str, Any]]]]:
    """Normalize interrupted states on startup and return jobs to enqueue."""
    jobs = (
        db.query(Job)
        .filter(Job.status.in_(["queued", "running", "pausing", "canceling"]))
        .all()
    )
    enqueue_ids: list[str] = []
    events: list[tuple[str, str, dict[str, Any]]] = []
    for job in jobs:
        control = load_control(job)
        if job.status == "canceling":
            job.status = "canceled"
            job.finished_at = utcnow()
            job.error = "Cancelado por el usuario"
            control["canceled_at"] = control.get("canceled_at") or _iso_now()
            store_control(job, control)
            events.append(
                (
                    job.id,
                    "Cancelación recuperada tras reiniciar el backend",
                    control.get("checkpoint", {}),
                )
            )
            continue
        if job.status == "pausing":
            job.status = "paused"
            control["paused_at"] = control.get("paused_at") or _iso_now()
            control["paused_from"] = control.get("paused_from") or "running"
            control["last_action"] = "pause"
            store_control(job, control)
            events.append(
                (
                    job.id,
                    "Pausa recuperada tras reiniciar el backend",
                    control.get("checkpoint", {}),
                )
            )
            continue
        if job.status == "running":
            job.status = "queued"
            control["recovered_at"] = _iso_now()
            control["last_action"] = "recover"
            store_control(job, control)
            events.append(
                (
                    job.id,
                    "Ejecución recuperada desde el último punto seguro",
                    control.get("checkpoint", {}),
                )
            )
        enqueue_ids.append(job.id)
    db.commit()
    return enqueue_ids, events
