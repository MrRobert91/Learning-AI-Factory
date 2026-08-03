"""Persistent, idempotent usage accounting and artifact attribution."""

from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from factory_api.artifact_versions import artifact_metadata
from factory_api.config import get_settings
from factory_api.db import SessionLocal
from factory_api.events import event_broker, event_repository
from factory_api.models import Artifact, Job, UsageRecord

logger = logging.getLogger(__name__)


def _non_negative(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return max(result, Decimal("0"))


def _stable_key(*parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _serialize(record: UsageRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "project_id": record.project_id,
        "job_id": record.job_id,
        "workflow_step": record.workflow_step,
        "agent": record.agent,
        "operation": record.operation,
        "provider": record.provider,
        "model": record.model,
        "provider_request_id": record.provider_request_id,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "total_tokens": record.total_tokens,
        "input_characters": record.input_characters,
        "output_units": record.output_units,
        "image_count": record.image_count,
        "cost_usd": str(record.cost_usd) if record.cost_usd is not None else None,
        "cost_source": record.cost_source,
        "pricing_snapshot": json.loads(record.pricing_snapshot_json or "{}"),
        "artifact_id": record.artifact_id,
        "work_unit_key": record.work_unit_key,
        "metadata": json.loads(record.metadata_json or "{}"),
        "created_at": record.created_at.isoformat(),
    }


def record_usage(
    *,
    job_id: str | None = None,
    project_id: str | None = None,
    workflow_step: int | None = None,
    agent: str = "",
    operation: str = "llm",
    provider: str = "openrouter",
    model: str = "",
    provider_request_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    input_characters: int = 0,
    output_units: int = 0,
    image_count: int = 0,
    cost_usd: Any = None,
    cost_source: str | None = None,
    pricing_snapshot: dict[str, Any] | None = None,
    artifact_id: str | None = None,
    work_unit_key: str = "",
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    emit_event: bool = True,
) -> str | None:
    """Store one immutable usage call. Failures are logged, never raised."""

    input_count = _non_negative(input_tokens)
    output_count = _non_negative(output_tokens)
    total_count = input_count + output_count
    characters = _non_negative(input_characters)
    units = _non_negative(output_units)
    images = _non_negative(image_count)
    cost = _decimal(cost_usd)
    snapshot = dict(pricing_snapshot or {})
    source = cost_source
    if cost is not None and source is None:
        source = "provider_actual"
    if cost is None and total_count:
        price = Decimal(str(get_settings().budget_price_per_mtok_usd))
        cost = (Decimal(total_count) / Decimal(1_000_000)) * price
        source = source or "estimated_global"
        snapshot = {
            **snapshot,
            "currency": "USD",
            "price_per_million_tokens_usd": str(price),
        }
    source = source or "unknown"
    key = (
        _stable_key("explicit", idempotency_key)
        if idempotency_key
        else _stable_key(
            "provider-request" if provider_request_id else "work-unit",
            provider,
            provider_request_id or "",
            job_id or "",
            work_unit_key,
            operation,
            model,
            input_count,
            output_count,
            characters,
            images,
        )
    )
    try:
        with SessionLocal() as db:
            existing = db.scalar(
                select(UsageRecord).where(UsageRecord.idempotency_key == key)
            )
            if existing is not None:
                return existing.id
            if project_id is None and job_id:
                job = db.get(Job, job_id)
                project_id = job.project_id if job is not None else None
            record = UsageRecord(
                project_id=project_id,
                job_id=job_id,
                workflow_step=workflow_step,
                agent=agent,
                operation=operation,
                provider=provider,
                model=model,
                provider_request_id=provider_request_id,
                input_tokens=input_count,
                output_tokens=output_count,
                total_tokens=total_count,
                input_characters=characters,
                output_units=units,
                image_count=images,
                cost_usd=cost,
                cost_source=source,
                pricing_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
                artifact_id=artifact_id,
                work_unit_key=work_unit_key,
                idempotency_key=key,
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
            )
            db.add(record)
            db.flush()
            event_added = False
            if emit_event and job_id:
                event_repository.append(
                    db,
                    job_id,
                    "usage",
                    (
                        f"Uso registrado: {agent or operation} · "
                        f"{model or provider} · {total_count} tokens"
                    ),
                    {
                        "usage_record_id": record.id,
                        "agent": agent,
                        "operation": operation,
                        "model": model,
                        "total_tokens": total_count,
                        "image_count": images,
                        "cost_usd": str(cost) if cost is not None else None,
                        "cost_source": source,
                    },
                )
                event_added = True
            db.commit()
            if event_added and job_id:
                event_broker.notify(job_id)
            return record.id
    except IntegrityError:
        with SessionLocal() as db:
            existing = db.scalar(
                select(UsageRecord).where(UsageRecord.idempotency_key == key)
            )
            return existing.id if existing is not None else None
    except Exception:
        logger.exception(
            "Usage persistence failed",
            extra={"job_id": job_id, "agent": agent, "operation": operation},
        )
        return None


def attach_usage_to_artifact(
    db: Session,
    artifact: Artifact,
    *,
    job_id: str | None = None,
    agent: str | None = None,
    operation: str | None = None,
    usage_record_ids: list[str] | None = None,
) -> list[str]:
    """Link pending calls and preserve their IDs in immutable artifact metadata."""

    ids = {str(value) for value in (usage_record_ids or []) if value}
    stmt = select(UsageRecord).where(UsageRecord.artifact_id.is_(None))
    if job_id:
        stmt = stmt.where(UsageRecord.job_id == job_id)
    else:
        stmt = stmt.where(UsageRecord.id.in_(ids)) if ids else stmt.where(False)
    if agent:
        stmt = stmt.where(UsageRecord.agent == agent)
    if operation:
        stmt = stmt.where(UsageRecord.operation == operation)
    pending = list(db.scalars(stmt).all())
    for record in pending:
        record.artifact_id = artifact.id
        ids.add(record.id)
    metadata = artifact_metadata(artifact)
    ids.update(str(value) for value in metadata.get("usage_record_ids", []) if value)
    metadata["usage_record_ids"] = sorted(ids)
    artifact.metadata_json = json.dumps(metadata, ensure_ascii=False)
    return sorted(ids)


def usage_record_by_work_unit(work_unit_key: str) -> str | None:
    if not work_unit_key:
        return None
    with SessionLocal() as db:
        return db.scalar(
            select(UsageRecord.id)
            .where(UsageRecord.work_unit_key == work_unit_key)
            .order_by(UsageRecord.created_at.desc())
            .limit(1)
        )


def job_usage_summary(db: Session, job_id: str) -> dict[str, Any]:
    return job_usage_summaries(db, [job_id]).get(
        job_id, {"has_data": False, "records": 0}
    )


def job_usage_summaries(
    db: Session, job_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """Aggregate a page of jobs with one SQL GROUP BY query."""

    if not job_ids:
        return {}
    rows = db.execute(
        select(
            UsageRecord.job_id,
            func.count(UsageRecord.id),
            func.sum(UsageRecord.input_tokens),
            func.sum(UsageRecord.output_tokens),
            func.sum(UsageRecord.total_tokens),
            func.sum(UsageRecord.input_characters),
            func.sum(UsageRecord.image_count),
            func.sum(UsageRecord.cost_usd),
            func.sum(case((UsageRecord.cost_usd.is_(None), 1), else_=0)),
        )
        .where(UsageRecord.job_id.in_(job_ids))
        .group_by(UsageRecord.job_id)
    ).all()
    summaries: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_job_id = str(row[0])
        summaries[row_job_id] = {
            "has_data": True,
            "records": int(row[1] or 0),
            "input_tokens": int(row[2] or 0),
            "output_tokens": int(row[3] or 0),
            "total_tokens": int(row[4] or 0),
            "input_characters": int(row[5] or 0),
            "image_count": int(row[6] or 0),
            "cost_usd": str(row[7]) if row[7] is not None else None,
            "unknown_cost_records": int(row[8] or 0),
        }
    return summaries


def serialize_usage_record(record: UsageRecord) -> dict[str, Any]:
    return _serialize(record)
