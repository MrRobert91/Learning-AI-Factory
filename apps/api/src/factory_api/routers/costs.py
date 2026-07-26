"""Authorized project usage aggregation, filtering, and export."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from factory_api.artifact_versions import artifact_metadata
from factory_api.auth import CurrentUser
from factory_api.db import get_db
from factory_api.models import Artifact, Job, Project, UsageRecord
from factory_api.usage import serialize_usage_record

router = APIRouter(prefix="/api/projects", tags=["costs"])
preview_router = APIRouter(prefix="/api/costs", tags=["costs"])
DB = Annotated[Session, Depends(get_db)]


def _owned_project(db: Session, user_id: str, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return project


def _money(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _sum_cost(records: list[UsageRecord]) -> Decimal | None:
    values = [record.cost_usd for record in records if record.cost_usd is not None]
    return sum(values, Decimal("0")) if values else None


def _aggregate(records: list[UsageRecord]) -> dict:
    return {
        "calls": len(records),
        "input_tokens": sum(record.input_tokens for record in records),
        "output_tokens": sum(record.output_tokens for record in records),
        "total_tokens": sum(record.total_tokens for record in records),
        "input_characters": sum(record.input_characters for record in records),
        "image_count": sum(record.image_count for record in records),
        "cost_usd": _money(_sum_cost(records)),
        "unknown_cost_records": sum(record.cost_usd is None for record in records),
    }


def _active_usage_ids(db: Session, project_id: str) -> set[str]:
    artifacts = db.scalars(
        select(Artifact).where(
            Artifact.project_id == project_id,
            Artifact.is_selected.is_(True),
        )
    ).all()
    ids: set[str] = set()
    for artifact in artifacts:
        ids.update(
            str(value)
            for value in artifact_metadata(artifact).get("usage_record_ids", [])
            if value
        )
    return ids


def _group(records: list[UsageRecord], key) -> list[dict]:
    grouped: dict[str, list[UsageRecord]] = defaultdict(list)
    for record in records:
        grouped[str(key(record) or "sin-dato")].append(record)
    return [
        {"key": name, **_aggregate(items)}
        for name, items in sorted(
            grouped.items(),
            key=lambda item: (_sum_cost(item[1]) or Decimal("0"), item[0]),
            reverse=True,
        )
    ]


def _summary(db: Session, project_id: str) -> dict:
    historical = list(
        db.scalars(
            select(UsageRecord)
            .where(UsageRecord.project_id == project_id)
            .order_by(UsageRecord.created_at, UsageRecord.id)
        ).all()
    )
    if not historical:
        return {
            "has_data": False,
            "historical": None,
            "active": None,
            "cost_sources": [],
            "agents": [],
            "models": [],
            "runs": [],
            "last_updated": None,
        }
    active_ids = _active_usage_ids(db, project_id)
    active = (
        list(db.scalars(select(UsageRecord).where(UsageRecord.id.in_(active_ids))).all())
        if active_ids
        else []
    )
    records_by_job: dict[str, list[UsageRecord]] = defaultdict(list)
    for record in historical:
        records_by_job[str(record.job_id or "sin-run")].append(record)
    jobs = db.scalars(
        select(Job)
        .where(Job.project_id == project_id)
        .order_by(Job.created_at.desc(), Job.id.desc())
    ).all()
    run_breakdown = [
        {
            "key": job.id,
            "kind": job.kind,
            "status": job.status,
            "created_at": job.created_at.isoformat(),
            "has_data": bool(records_by_job.get(job.id)),
            **_aggregate(records_by_job.get(job.id, [])),
        }
        for job in jobs
    ]
    if records_by_job.get("sin-run"):
        run_breakdown.append(
            {
                "key": "sin-run",
                "kind": "preview",
                "status": "done",
                "created_at": None,
                "has_data": True,
                **_aggregate(records_by_job["sin-run"]),
            }
        )
    return {
        "has_data": True,
        "historical": _aggregate(historical),
        "active": _aggregate(active) if active else None,
        "cost_sources": _group(historical, lambda record: record.cost_source),
        "agents": _group(historical, lambda record: record.agent),
        "models": sorted({record.model for record in historical if record.model}),
        "runs": run_breakdown,
        "last_updated": max(record.created_at for record in historical).isoformat(),
    }


def _filtered_stmt(
    project_id: str,
    *,
    run: str | None,
    agent: str | None,
    model: str | None,
    operation: str | None,
    cost_source: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
):
    stmt = select(UsageRecord).where(UsageRecord.project_id == project_id)
    if run:
        stmt = stmt.where(UsageRecord.job_id == run)
    if agent:
        stmt = stmt.where(UsageRecord.agent == agent)
    if model:
        stmt = stmt.where(UsageRecord.model == model)
    if operation:
        stmt = stmt.where(UsageRecord.operation == operation)
    if cost_source:
        stmt = stmt.where(UsageRecord.cost_source == cost_source)
    if date_from:
        stmt = stmt.where(UsageRecord.created_at >= date_from)
    if date_to:
        stmt = stmt.where(UsageRecord.created_at <= date_to)
    return stmt


@router.get("/{project_id}/costs/summary")
def project_cost_summary(project_id: str, user: CurrentUser, db: DB):
    _owned_project(db, user.id, project_id)
    return _summary(db, project_id)


@router.get("/{project_id}/costs/by-agent")
def project_costs_by_agent(project_id: str, user: CurrentUser, db: DB):
    _owned_project(db, user.id, project_id)
    records = list(
        db.scalars(select(UsageRecord).where(UsageRecord.project_id == project_id)).all()
    )
    return _group(records, lambda record: record.agent)


@preview_router.get("/previews/summary")
def profile_preview_cost_summary(user: CurrentUser, db: DB):
    records = list(
        db.scalars(
            select(UsageRecord)
            .where(UsageRecord.project_id.is_(None))
            .order_by(UsageRecord.created_at, UsageRecord.id)
        ).all()
    )
    return {
        "has_data": bool(records),
        "historical": _aggregate(records) if records else None,
        "agents": _group(records, lambda record: record.agent),
        "models": sorted({record.model for record in records if record.model}),
        "last_updated": (
            max(record.created_at for record in records).isoformat() if records else None
        ),
    }


@router.get("/{project_id}/costs/records")
def project_cost_records(
    project_id: str,
    user: CurrentUser,
    db: DB,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    run: str | None = None,
    agent: str | None = None,
    model: str | None = None,
    operation: str | None = None,
    cost_source: str | None = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
):
    _owned_project(db, user.id, project_id)
    stmt = _filtered_stmt(
        project_id,
        run=run,
        agent=agent,
        model=model,
        operation=operation,
        cost_source=cost_source,
        date_from=date_from,
        date_to=date_to,
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    records = db.scalars(
        stmt.order_by(UsageRecord.created_at.desc(), UsageRecord.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [serialize_usage_record(record) for record in records],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/{project_id}/costs/export")
def export_project_costs(
    project_id: str,
    user: CurrentUser,
    db: DB,
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    run: str | None = None,
    agent: str | None = None,
    model: str | None = None,
    operation: str | None = None,
    cost_source: str | None = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
):
    _owned_project(db, user.id, project_id)
    stmt = _filtered_stmt(
        project_id,
        run=run,
        agent=agent,
        model=model,
        operation=operation,
        cost_source=cost_source,
        date_from=date_from,
        date_to=date_to,
    )
    records = list(
        db.scalars(
            stmt.order_by(UsageRecord.created_at, UsageRecord.id)
        ).all()
    )
    serialized = [serialize_usage_record(record) for record in records]
    filename = f"project-{project_id}-usage.{format}"
    if format == "json":
        return JSONResponse(
            {"summary": _aggregate(records), "records": serialized},
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    fields = [
        "id",
        "project_id",
        "job_id",
        "workflow_step",
        "agent",
        "operation",
        "provider",
        "model",
        "provider_request_id",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "input_characters",
        "output_units",
        "image_count",
        "cost_usd",
        "cost_source",
        "artifact_id",
        "work_unit_key",
        "created_at",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(serialized)
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
