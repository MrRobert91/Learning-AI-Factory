import threading

from factory_agents.runtime import RunEvent
from factory_api.db import SessionLocal
from factory_api.models import Job
from factory_api.run_control import recover_jobs
from test_pipeline import _patch_all
from test_runs import _create_project, _wait_for_job
from test_workflows import (
    _human_profile,
    _template_id,
    _wait_for_status,
)


def test_pause_running_workflow_resumes_without_repeating_completed_agent(
    auth_client, monkeypatch
):
    _patch_all(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_curator(task_input, **kwargs):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(5)
        yield RunEvent(type="result", summary="# Brief recuperable")

    monkeypatch.setattr("factory_agents.agents.curator.run_curator", slow_curator)
    project = _create_project(auth_client)
    workflow_id = _template_id(auth_client, "Investigación y plan")
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow_id},
    ).json()["id"]

    assert started.wait(5)
    pause = auth_client.post(f"/api/runs/{job_id}/pause")
    assert pause.status_code == 200
    assert pause.json()["status"] == "pausing"
    repeated = auth_client.post(f"/api/runs/{job_id}/pause")
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "pausing"
    release.set()

    paused = _wait_for_status(auth_client, job_id, ["paused", "failed"])
    assert paused["status"] == "paused"
    assert paused["control"]["checkpoint"]["last_completed_unit"].endswith(
        ":curator:brief"
    )
    assert calls == 1
    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    assert [item["type"] for item in artifacts] == ["research_brief"]

    resumed = auth_client.post(f"/api/runs/{job_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] in {"queued", "running"}
    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"
    assert calls == 1
    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    briefs = [item for item in artifacts if item["type"] == "research_brief"]
    assert len(briefs) == 1
    assert briefs[0]["version"] == 1
    assert any(item["type"] == "course_plan" for item in artifacts)


def test_pause_waiting_approval_restores_approval_without_requeue(
    auth_client, monkeypatch
):
    _patch_all(monkeypatch)
    project = _create_project(auth_client)
    profile = _human_profile(auth_client, "curator")
    workflow = auth_client.post(
        "/api/workflows",
        json={
            "name": "Aprobación pausable",
            "steps": [{"agent": "curator", "profile_id": profile["id"]}],
        },
    ).json()
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow["id"]},
    ).json()["id"]
    _wait_for_status(auth_client, job_id, ["waiting_approval"])

    paused = auth_client.post(f"/api/runs/{job_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    resumed = auth_client.post(f"/api/runs/{job_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "waiting_approval"
    repeated = auth_client.post(f"/api/runs/{job_id}/resume")
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "waiting_approval"

    approved = auth_client.post(
        f"/api/runs/{job_id}/approve", json={"approved": True}
    )
    assert approved.status_code == 200
    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"
    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    briefs = [item for item in artifacts if item["type"] == "research_brief"]
    assert len(briefs) == 1
    assert briefs[0]["version"] == 1


def test_cancel_running_workflow_is_terminal_at_next_safe_point(
    auth_client, monkeypatch
):
    _patch_all(monkeypatch)
    started = threading.Event()
    release = threading.Event()

    def slow_curator(task_input, **kwargs):
        started.set()
        assert release.wait(5)
        yield RunEvent(type="result", summary="# Brief cancelable")

    monkeypatch.setattr("factory_agents.agents.curator.run_curator", slow_curator)
    project = _create_project(auth_client)
    workflow_id = _template_id(auth_client, "Investigación y plan")
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow_id},
    ).json()["id"]

    assert started.wait(5)
    cancel = auth_client.post(f"/api/runs/{job_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "canceling"
    release.set()

    canceled = _wait_for_status(auth_client, job_id, ["canceled", "failed"])
    assert canceled["status"] == "canceled"
    assert auth_client.post(f"/api/runs/{job_id}/resume").status_code == 409
    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    assert [item["type"] for item in artifacts] == ["research_brief"]


def test_restart_requeues_running_and_settles_control_transitions(auth_client):
    project = _create_project(auth_client)
    with SessionLocal() as db:
        running = Job(
            kind="curator_run",
            project_id=project["id"],
            status="running",
            control_json='{"checkpoint":{"phase":"curator","next_unit":"brief"}}',
        )
        pausing = Job(
            kind="curator_run",
            project_id=project["id"],
            status="pausing",
            control_json='{"paused_from":"running"}',
        )
        canceling = Job(
            kind="curator_run",
            project_id=project["id"],
            status="canceling",
        )
        db.add_all([running, pausing, canceling])
        db.commit()

        ids, events = recover_jobs(db)
        db.refresh(running)
        db.refresh(pausing)
        db.refresh(canceling)

        assert running.status == "queued"
        assert running.id in ids
        assert pausing.status == "paused"
        assert pausing.id not in ids
        assert canceling.status == "canceled"
        assert canceling.id not in ids
        assert {event[0] for event in events} == {
            running.id,
            pausing.id,
            canceling.id,
        }
        running.status = "canceled"
        pausing.status = "canceled"
        db.commit()
