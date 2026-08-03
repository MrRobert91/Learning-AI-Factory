import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from factory_api.auth import create_session_token
from factory_api.config import get_settings
from factory_api.db import SessionLocal, engine
from factory_api.events import event_broker, event_repository
from factory_api.models import Job, JobEvent, Project, UsageRecord, User
from factory_api.usage import record_usage
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select, text


def _owned_job(*, status: str = "done") -> tuple[str, str]:
    with SessionLocal() as db:
        owner = db.scalars(select(User).order_by(User.created_at).limit(1)).one()
        project = Project(owner_id=owner.id, title="Atomic events")
        db.add(project)
        db.flush()
        job = Job(kind="test_run", project_id=project.id, status=status)
        db.add(job)
        db.commit()
        return project.id, job.id


def test_atomic_event_sequences_are_contiguous_under_concurrency(auth_client):
    _, job_id = _owned_job()

    def produce(worker: int) -> None:
        for item in range(50):
            event_repository.append_committed(
                job_id,
                "test",
                f"worker {worker} event {item}",
            )

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(produce, range(20)))

    with SessionLocal() as db:
        events = list(
            db.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job_id)
                .order_by(JobEvent.seq)
            ).all()
        )
        job = db.get(Job, job_id)
        assert [event.seq for event in events] == list(range(1000))
        assert job is not None and job.next_event_seq == 1000
        plan = db.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT * FROM job_events "
                "WHERE job_id = :job_id AND seq > :seq ORDER BY seq LIMIT 200"
            ),
            {"job_id": job_id, "seq": 500},
        ).all()
        assert "ix_job_events_job_id_seq" in " ".join(str(row) for row in plan)


def test_usage_and_regular_events_share_one_sequence(auth_client):
    project_id, job_id = _owned_job()

    with ThreadPoolExecutor(max_workers=2) as pool:
        regular = pool.submit(
            event_repository.append_committed,
            job_id,
            "stage",
            "regular event",
        )
        usage = pool.submit(
            record_usage,
            job_id=job_id,
            project_id=project_id,
            agent="curator",
            operation="llm",
            provider="test",
            model="test-model",
            input_tokens=10,
            idempotency_key=f"usage:{job_id}",
        )
        regular.result()
        assert usage.result() is not None

    with SessionLocal() as db:
        events = list(
            db.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job_id)
                .order_by(JobEvent.seq)
            ).all()
        )
        assert [event.seq for event in events] == [0, 1]
        assert {event.type for event in events} == {"stage", "usage"}


def test_usage_and_its_event_roll_back_together(auth_client, monkeypatch):
    project_id, job_id = _owned_job()

    def fail_event(*_args, **_kwargs):
        raise RuntimeError("event failed")

    monkeypatch.setattr(event_repository, "append", fail_event)
    usage_id = record_usage(
        job_id=job_id,
        project_id=project_id,
        agent="curator",
        operation="llm",
        provider="test",
        model="test-model",
        input_tokens=10,
        idempotency_key=f"rollback:{job_id}",
    )
    assert usage_id is None
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count(UsageRecord.id)).where(UsageRecord.job_id == job_id)
            )
            == 0
        )


def test_event_broker_wakes_and_cleans_subscribers():
    async def scenario() -> None:
        async with event_broker.subscribe("broker-test") as signal:
            assert event_broker.subscriber_count("broker-test") == 1
            event_broker.notify("broker-test")
            await asyncio.wait_for(signal.wait(), timeout=1)
        assert event_broker.subscriber_count("broker-test") == 0

    asyncio.run(scenario())


def test_sse_resumes_from_last_event_id_and_validates_cursor(auth_client):
    _, job_id = _owned_job(status="done")
    for seq in range(5):
        event_repository.append_committed(job_id, "test", f"event {seq}")

    response = auth_client.get(
        f"/api/runs/{job_id}/events?after_seq=not-used",
        headers={"Last-Event-ID": "2"},
    )
    assert response.status_code == 200
    assert "id: 3" in response.text
    assert "id: 4" in response.text
    assert "event 2" not in response.text
    assert "event: done" in response.text

    from_zero = auth_client.get(
        f"/api/runs/{job_id}/events", headers={"Last-Event-ID": "0"}
    )
    assert "id: 0" not in from_zero.text and "id: 1" in from_zero.text
    at_last = auth_client.get(
        f"/api/runs/{job_id}/events", headers={"Last-Event-ID": "4"}
    )
    assert "event: done" in at_last.text and "data: {\"seq\"" not in at_last.text
    future = auth_client.get(
        f"/api/runs/{job_id}/events", headers={"Last-Event-ID": "99"}
    )
    assert "event: done" in future.text and "data: {\"seq\"" not in future.text

    invalid = auth_client.get(
        f"/api/runs/{job_id}/events", headers={"Last-Event-ID": "invalid"}
    )
    assert invalid.status_code == 400


def test_job_endpoints_hide_foreign_and_global_jobs(auth_client):
    _, owned_job_id = _owned_job()
    with SessionLocal() as db:
        intruder = User(email="intruder@example.test", display_name="Intruder")
        global_job = Job(kind="global_test", project_id=None, status="done")
        db.add_all([intruder, global_job])
        db.commit()
        intruder_id = intruder.id
        global_job_id = global_job.id

    auth_client.cookies.clear()
    auth_client.cookies.set(
        get_settings().session_cookie_name, create_session_token(intruder_id)
    )
    assert auth_client.get(f"/api/runs/{owned_job_id}").status_code == 404
    assert auth_client.get(f"/api/runs/{owned_job_id}/events").status_code == 404
    assert auth_client.post(f"/api/runs/{owned_job_id}/pause").status_code == 404
    assert auth_client.get(f"/api/runs/{global_job_id}").status_code == 404


def test_run_list_is_cursor_paginated_and_returns_active_job(auth_client):
    project_id, active_job_id = _owned_job(status="running")
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    with SessionLocal() as db:
        active = db.get(Job, active_job_id)
        assert active is not None
        active.created_at = created_at
        for _index in range(100):
            db.add(
                Job(
                    kind="test_run",
                    project_id=project_id,
                    status="done",
                    created_at=datetime(2026, 1, 2, tzinfo=UTC),
                    result_json='{"large": "not listed"}',
                )
            )
        db.commit()

    queries: list[str] = []

    def count_query(_conn, _cursor, statement, _parameters, _context, _executemany):
        queries.append(statement)

    sqlalchemy_event.listen(engine, "before_cursor_execute", count_query)
    try:
        first_response = auth_client.get(
            f"/api/projects/{project_id}/runs", params={"limit": 10}
        )
    finally:
        sqlalchemy_event.remove(engine, "before_cursor_execute", count_query)
    first = first_response.json()
    assert len(queries) <= 6
    assert len(first["items"]) == 10
    assert first["next_cursor"]
    assert first["active"]["id"] == active_job_id
    assert all(item["result"] is None and item["events"] == [] for item in first["items"])

    with SessionLocal() as db:
        newer = Job(
            kind="test_run",
            project_id=project_id,
            status="done",
            created_at=datetime(2026, 1, 3, tzinfo=UTC),
        )
        db.add(newer)
        db.commit()
        newer_id = newer.id

    second = auth_client.get(
        f"/api/projects/{project_id}/runs",
        params={"limit": 10, "cursor": first["next_cursor"]},
    ).json()
    assert len(second["items"]) == 10
    assert newer_id not in {item["id"] for item in second["items"]}
    assert not ({item["id"] for item in first["items"]} & {item["id"] for item in second["items"]})
    assert (
        auth_client.get(
            f"/api/projects/{project_id}/runs", params={"cursor": "%%%"}
        ).status_code
        == 400
    )


def test_event_history_is_incremental(auth_client):
    _, job_id = _owned_job(status="done")
    for seq in range(5):
        event_repository.append_committed(job_id, "test", f"event {seq}")

    first = auth_client.get(
        f"/api/runs/{job_id}/event-history", params={"limit": 2}
    ).json()
    assert [event["seq"] for event in first["items"]] == [0, 1]
    assert first["next_after_seq"] == 1
    second = auth_client.get(
        f"/api/runs/{job_id}/event-history",
        params={"after_seq": first["next_after_seq"], "limit": 2},
    ).json()
    assert [event["seq"] for event in second["items"]] == [2, 3]
