"""Atomic job-event persistence and in-process SSE notifications."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from factory_api.db import SessionLocal
from factory_api.models import Job, JobEvent


class EventBroker:
    """Wake local SSE subscribers without making SQLite the idle poller."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[
            str, dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Event]]
        ] = {}
        self._next_token = 0

    @asynccontextmanager
    async def subscribe(self, job_id: str) -> AsyncIterator[asyncio.Event]:
        loop = asyncio.get_running_loop()
        signal = asyncio.Event()
        with self._lock:
            self._next_token += 1
            token = self._next_token
            self._subscribers.setdefault(job_id, {})[token] = (loop, signal)
        try:
            yield signal
        finally:
            with self._lock:
                listeners = self._subscribers.get(job_id)
                if listeners is not None:
                    listeners.pop(token, None)
                    if not listeners:
                        self._subscribers.pop(job_id, None)

    def notify(self, job_id: str) -> None:
        with self._lock:
            listeners = list(self._subscribers.get(job_id, {}).values())
        for loop, signal in listeners:
            if not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(signal.set)
                except RuntimeError:
                    # The disconnect finalizer removes it; tolerate a loop that
                    # closed between the check and the thread-safe callback.
                    continue

    def subscriber_count(self, job_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get(job_id, {}))


class EventRepository:
    """Reserve and insert event sequences inside the caller's transaction."""

    def append(
        self,
        db: Session,
        job_id: str,
        type_: str,
        summary: str,
        data: dict | None = None,
    ) -> JobEvent:
        next_value = db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(next_event_seq=Job.next_event_seq + 1)
            .returning(Job.next_event_seq)
        ).scalar_one_or_none()
        if next_value is None:
            raise LookupError(f"Job {job_id} does not exist")
        event = JobEvent(
            job_id=job_id,
            seq=int(next_value) - 1,
            type=type_,
            summary=summary,
            data_json=json.dumps(data, ensure_ascii=False) if data else None,
        )
        db.add(event)
        db.flush()
        return event

    def append_committed(
        self,
        job_id: str,
        type_: str,
        summary: str,
        data: dict | None = None,
        *,
        attempts: int = 5,
    ) -> JobEvent:
        for attempt in range(attempts):
            try:
                with SessionLocal() as db:
                    event = self.append(db, job_id, type_, summary, data)
                    db.commit()
                event_broker.notify(job_id)
                return event
            except OperationalError as exc:
                is_locked = "locked" in str(exc).lower()
                if not is_locked or attempt + 1 >= attempts:
                    raise
                time.sleep(0.01 * (2**attempt))
        raise RuntimeError("Unreachable event append retry state")

    def page(
        self,
        db: Session,
        job_id: str,
        *,
        after_seq: int,
        limit: int,
    ) -> list[JobEvent]:
        return list(
            db.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job_id, JobEvent.seq > after_seq)
                .order_by(JobEvent.seq)
                .limit(limit)
            ).all()
        )


event_broker = EventBroker()
event_repository = EventRepository()
