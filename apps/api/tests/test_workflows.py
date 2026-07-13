from test_pipeline import _patch_all
from test_runs import _create_project, _wait_for_job


def _wait_for_status(auth_client, job_id, statuses, timeout=10):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        job = auth_client.get(f"/api/runs/{job_id}").json()
        if job["status"] in statuses:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} stuck at {job['status']}")


def _template_id(auth_client, name):
    workflows = auth_client.get("/api/workflows").json()
    return next(w["id"] for w in workflows if w["name"] == name)


def test_templates_seeded(auth_client):
    workflows = auth_client.get("/api/workflows").json()
    names = [w["name"] for w in workflows if w["is_template"]]
    assert "Curso completo (hasta slides)" in names
    full = next(w for w in workflows if w["name"] == "Curso completo (hasta slides)")
    assert [s["agent"] for s in full["steps"]] == ["curator", "planner", "lessons", "slides"]
    assert full["steps"][1]["approval_after"] is True


def test_workflow_crud_and_validation(auth_client):
    resp = auth_client.post(
        "/api/workflows",
        json={"name": "Mi flujo", "steps": [{"agent": "curator"}, {"agent": "planner"}]},
    )
    assert resp.status_code == 201
    wf = resp.json()

    resp = auth_client.patch(
        f"/api/workflows/{wf['id']}",
        json={"steps": [{"agent": "curator", "approval_after": True}]},
    )
    assert resp.status_code == 200
    assert resp.json()["steps"][0]["approval_after"] is True

    resp = auth_client.post(
        "/api/workflows", json={"name": "Malo", "steps": [{"agent": "nope"}]}
    )
    assert resp.status_code == 422

    template_id = _template_id(auth_client, "Investigación y plan")
    assert auth_client.patch(
        f"/api/workflows/{template_id}", json={"name": "X"}
    ).status_code == 409
    assert auth_client.delete(f"/api/workflows/{template_id}").status_code == 409

    assert auth_client.delete(f"/api/workflows/{wf['id']}").status_code == 204


def test_workflow_run_with_approvals(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    project = _create_project(auth_client)
    workflow_id = _template_id(auth_client, "Curso completo (hasta slides)")

    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow_id},
    ).json()["id"]

    # Pauses after planner (step 2)
    job = _wait_for_status(auth_client, job_id, ["waiting_approval", "done", "failed"])
    assert job["status"] == "waiting_approval"
    approval_events = [e for e in job["events"] if e["type"] == "approval_required"]
    assert approval_events and approval_events[-1]["data"]["agent"] == "planner"

    # Approve → runs lessons+slides, pauses after slides
    resp = auth_client.post(f"/api/runs/{job_id}/approve", json={"approved": True})
    assert resp.status_code == 200
    job = _wait_for_status(auth_client, job_id, ["waiting_approval", "done", "failed"])
    assert job["status"] == "waiting_approval"
    approval_events = [e for e in job["events"] if e["type"] == "approval_required"]
    assert approval_events[-1]["data"]["agent"] == "slides"

    # Final approval → done, with all artifacts produced
    auth_client.post(f"/api/runs/{job_id}/approve", json={"approved": True})
    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"
    assert set(job["result"].keys()) == {"curator", "planner", "lessons", "slides"}
    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    assert {a["type"] for a in artifacts} == {
        "research_brief",
        "course_plan",
        "lesson_content",
        "slide_deck",
    }


def test_workflow_rejection(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    project = _create_project(auth_client)
    workflow_id = _template_id(auth_client, "Curso completo (hasta slides)")
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow_id},
    ).json()["id"]
    _wait_for_status(auth_client, job_id, ["waiting_approval"])

    auth_client.post(
        f"/api/runs/{job_id}/approve",
        json={"approved": False, "feedback": "el plan es demasiado largo"},
    )
    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "failed"
    assert "demasiado largo" in job["error"]


def test_cancel_waiting_run(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    project = _create_project(auth_client)
    workflow_id = _template_id(auth_client, "Curso completo (hasta slides)")
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow_id},
    ).json()["id"]
    _wait_for_status(auth_client, job_id, ["waiting_approval"])

    resp = auth_client.post(f"/api/runs/{job_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"
    assert "Cancelado" in resp.json()["error"]

    # Approving a cancelled run is refused
    resp = auth_client.post(f"/api/runs/{job_id}/approve", json={"approved": True})
    assert resp.status_code == 409


def test_workflow_without_approvals_runs_to_completion(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    project = _create_project(auth_client)
    workflow_id = _template_id(auth_client, "Investigación y plan")
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow_id},
    ).json()["id"]
    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"
    assert set(job["result"].keys()) == {"curator", "planner"}
