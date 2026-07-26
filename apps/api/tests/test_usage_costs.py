import json
from decimal import Decimal
from types import SimpleNamespace

from factory_agents.tools.tts import synthesize_cached_with_status
from factory_api.artifact_versions import add_artifact_version
from factory_api.db import SessionLocal
from factory_api.models import Artifact, Job, UsageRecord
from factory_api.routers.runs import _job_read
from factory_api.runner import TrackedClient, _budget_callbacks, runner
from factory_api.usage import attach_usage_to_artifact, record_usage
from sqlalchemy import select
from test_runs import _create_project


def _job(project_id: str) -> Job:
    with SessionLocal() as db:
        job = Job(
            kind="planner_run",
            status="done",
            project_id=project_id,
            payload_json="{}",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job


def test_tracked_client_persists_effective_model_actual_cost_and_deduplicates(
    auth_client,
):
    project = _create_project(auth_client)
    job = _job(project["id"])
    response = SimpleNamespace(
        id="gen-test-1",
        model="provider/effective-model",
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, cost=0.0042),
    )
    inner = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: response)
        )
    )
    client = TrackedClient(inner, job.id, agent="planner", work_unit_key="planner")

    client.chat.completions.create(model="requested-model", messages=[{"content": "secret"}])
    client.chat.completions.create(model="requested-model", messages=[{"content": "secret"}])

    with SessionLocal() as db:
        records = list(
            db.scalars(select(UsageRecord).where(UsageRecord.job_id == job.id)).all()
        )
    assert len(records) == 1
    assert records[0].model == "provider/effective-model"
    assert records[0].total_tokens == 20
    assert records[0].cost_usd == Decimal("0.0042000000")
    assert records[0].cost_source == "provider_actual"
    assert "secret" not in records[0].metadata_json


def test_langchain_callback_records_usage_once(auth_client):
    project = _create_project(auth_client)
    job = _job(project["id"])
    message = SimpleNamespace(
        id="lc-generation-1",
        usage_metadata={"input_tokens": 7, "output_tokens": 3},
        response_metadata={"model_name": "openrouter/callback-model"},
    )
    response = SimpleNamespace(
        generations=[
            [
                SimpleNamespace(message=message),
                SimpleNamespace(message=message),
            ]
        ],
        llm_output={},
    )

    callback = _budget_callbacks(
        job.id, agent="lessons", work_unit_key="lesson:1.1"
    )[0]
    callback.on_llm_end(response)

    with SessionLocal() as db:
        record = db.scalar(
            select(UsageRecord).where(UsageRecord.provider_request_id == "lc-generation-1")
        )
    assert record is not None
    assert record.total_tokens == 10
    assert record.cost_source == "estimated_global"
    assert json.loads(record.pricing_snapshot_json)["currency"] == "USD"


def test_project_cost_summary_active_selection_filters_and_exports(auth_client):
    project = _create_project(auth_client)
    job = _job(project["id"])
    old_job = _job(project["id"])
    first_id = record_usage(
        project_id=project["id"],
        job_id=job.id,
        agent="planner",
        operation="llm",
        provider="openrouter",
        model="model-a",
        input_tokens=100,
        output_tokens=50,
        cost_usd="0.10",
        idempotency_key=f"{project['id']}:first",
        emit_event=False,
    )
    second_id = record_usage(
        project_id=project["id"],
        job_id=job.id,
        agent="slides",
        operation="image",
        provider="openrouter",
        model="image-a",
        image_count=1,
        cost_usd="0.20",
        cost_source="estimated_catalog",
        idempotency_key=f"{project['id']}:second",
        emit_event=False,
    )
    unknown_id = record_usage(
        project_id=project["id"],
        job_id=job.id,
        agent="video",
        operation="tts",
        provider="openai",
        model="tts-a",
        input_characters=250,
        idempotency_key=f"{project['id']}:unknown",
        emit_event=False,
    )
    assert first_id and second_id and unknown_id

    with SessionLocal() as db:
        first = add_artifact_version(
            db,
            project_id=project["id"],
            type_="course_plan",
            format_="json",
            title="Plan",
            path="artifacts/first.json",
            metadata={"usage_record_ids": [first_id]},
        )
        second = add_artifact_version(
            db,
            project_id=project["id"],
            type_="course_plan",
            format_="json",
            title="Plan",
            path="artifacts/second.json",
            metadata={"usage_record_ids": [second_id]},
        )
        db.commit()
        first_artifact_id = first.id
        second_artifact_id = second.id

    summary = auth_client.get(f"/api/projects/{project['id']}/costs/summary")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["has_data"] is True
    assert Decimal(payload["historical"]["cost_usd"]) == Decimal("0.3000000000")
    assert Decimal(payload["active"]["cost_usd"]) == Decimal("0.2000000000")
    assert payload["historical"]["total_tokens"] == 150
    assert payload["historical"]["input_characters"] == 250
    assert payload["historical"]["image_count"] == 1
    assert payload["historical"]["unknown_cost_records"] == 1
    old_run = next(run for run in payload["runs"] if run["key"] == old_job.id)
    assert old_run["has_data"] is False
    assert old_run["cost_usd"] is None

    filtered = auth_client.get(
        f"/api/projects/{project['id']}/costs/records",
        params={"operation": "image", "page_size": 1},
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["id"] == second_id

    csv_export = auth_client.get(
        f"/api/projects/{project['id']}/costs/export",
        params={"format": "csv", "agent": "planner"},
    )
    assert csv_export.status_code == 200
    assert "model-a" in csv_export.text
    assert "image-a" not in csv_export.text

    json_export = auth_client.get(
        f"/api/projects/{project['id']}/costs/export",
        params={"format": "json"},
    ).json()
    assert len(json_export["records"]) == 3
    assert Decimal(json_export["summary"]["cost_usd"]) == Decimal("0.3000000000")

    selected = auth_client.post(f"/api/artifacts/{first_artifact_id}/select")
    assert selected.status_code == 200
    reselection = auth_client.get(
        f"/api/projects/{project['id']}/costs/summary"
    ).json()
    assert Decimal(reselection["active"]["cost_usd"]) == Decimal("0.1000000000")
    with SessionLocal() as db:
        assert db.get(Artifact, second_artifact_id).is_selected is False


def test_attach_usage_preserves_transitive_ids(auth_client):
    project = _create_project(auth_client)
    job = _job(project["id"])
    inherited_id = record_usage(
        agent="slides",
        operation="image",
        provider="openrouter",
        model="logo-model",
        image_count=1,
        cost_usd="0.03",
        idempotency_key=f"{project['id']}:logo",
        emit_event=False,
    )
    pending_id = record_usage(
        project_id=project["id"],
        job_id=job.id,
        agent="slides",
        operation="llm",
        model="slides-model",
        input_tokens=10,
        output_tokens=5,
        idempotency_key=f"{project['id']}:slides",
        emit_event=False,
    )
    with SessionLocal() as db:
        artifact = add_artifact_version(
            db,
            project_id=project["id"],
            type_="slide_deck",
            format_="markdown",
            title="Slides — 1.1",
            path="artifacts/slides.md",
            created_by_job_id=job.id,
            metadata={"usage_record_ids": [inherited_id]},
        )
        linked = attach_usage_to_artifact(
            db,
            artifact,
            job_id=job.id,
            agent="slides",
            usage_record_ids=[inherited_id],
        )
        db.commit()
        metadata = json.loads(artifact.metadata_json)
    assert set(linked) == {inherited_id, pending_id}
    assert set(metadata["usage_record_ids"]) == {inherited_id, pending_id}
    previews = auth_client.get("/api/costs/previews/summary").json()
    assert previews["has_data"] is True
    assert "logo-model" in previews["models"]


def test_project_without_usage_reports_no_data(auth_client):
    project = _create_project(auth_client)
    response = auth_client.get(f"/api/projects/{project['id']}/costs/summary")
    assert response.status_code == 200
    assert response.json()["has_data"] is False
    assert response.json()["historical"] is None


def test_tts_cache_reports_incremental_hit(tmp_path):
    class Provider:
        cache_key = "fake:model:voice"

        def __init__(self):
            self.calls = 0

        def synthesize(self, text: str) -> bytes:
            self.calls += 1
            return f"audio:{text}".encode()

    provider = Provider()
    first, first_hit = synthesize_cached_with_status(provider, "hola", tmp_path)
    second, second_hit = synthesize_cached_with_status(provider, "hola", tmp_path)
    assert first == second
    assert first_hit is False
    assert second_hit is True
    assert provider.calls == 1


def test_finished_job_includes_usage_summary(auth_client):
    project = _create_project(auth_client)
    job = _job(project["id"])
    record_usage(
        project_id=project["id"],
        job_id=job.id,
        agent="planner",
        input_tokens=2,
        output_tokens=3,
        cost_usd="0.01",
        idempotency_key=f"{project['id']}:finish",
        emit_event=False,
    )
    runner._finish(job.id, result={"artifact_id": "example"})
    with SessionLocal() as db:
        finished = db.get(Job, job.id)
        assert json.loads(finished.result_json) == {"artifact_id": "example"}
        response = _job_read(finished)
    assert response.usage_summary["total_tokens"] == 5
    assert response.usage_summary["cost_usd"] == "0.0100000000"
