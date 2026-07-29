import time

from factory_agents.runtime import RunEvent


def _fake_curator(task_input, **kwargs):
    yield RunEvent(type="tool_call", summary="search_web(query=LLMs)", data={"tool": "search_web"})
    yield RunEvent(type="assistant", summary="He encontrado buenas fuentes.")
    yield RunEvent(type="result", summary="# Research Brief: LLMs\n\n## Resumen ejecutivo\n…")


def _failing_curator(task_input, **kwargs):
    yield RunEvent(type="tool_call", summary="search_web(query=x)")
    raise RuntimeError("proveedor caído")


def _wait_for_job(auth_client, job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = auth_client.get(f"/api/runs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {job}")


def _create_project(auth_client):
    return auth_client.post(
        "/api/projects",
        json={
            "title": "Curso LLMs",
            "topic": "LLMs",
            "language": "es",
            "duration_spec": {
                "preset": "custom",
                "module_count": 1,
                "videos_per_module": 2,
                "target_minutes_per_video": 10,
            },
        },
    ).json()


def test_curator_run_produces_artifact(auth_client, monkeypatch):
    monkeypatch.setattr("factory_agents.agents.curator.run_curator", _fake_curator)
    project = _create_project(auth_client)

    resp = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs", json={"agent": "curator"}
    )
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"
    assert job["result"]["artifact_id"]
    types = [e["type"] for e in job["events"]]
    assert "tool_call" in types and "artifact" in types

    artifact = auth_client.get(f"/api/artifacts/{job['result']['artifact_id']}").json()
    assert artifact["type"] == "research_brief"
    assert artifact["content"].startswith("# Research Brief")

    listed = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    assert any(a["id"] == artifact["id"] for a in listed)

    runs = auth_client.get(f"/api/projects/{project['id']}/runs").json()
    assert runs[0]["id"] == job_id

    download = auth_client.get(f"/api/artifacts/{artifact['id']}/download")
    assert download.status_code == 200
    assert "Research Brief" in download.text


def test_curator_run_failure_is_reported(auth_client, monkeypatch):
    monkeypatch.setattr("factory_agents.agents.curator.run_curator", _failing_curator)
    project = _create_project(auth_client)
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs", json={"agent": "curator"}
    ).json()["id"]
    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "failed"
    assert "proveedor caído" in job["error"]


def test_curator_run_with_specific_profile(auth_client, monkeypatch):
    captured = {}

    def spy_curator(task_input, **kwargs):
        captured.update(kwargs, task_input=task_input)
        yield RunEvent(type="result", summary="# Brief")

    monkeypatch.setattr("factory_agents.agents.curator.run_curator", spy_curator)
    profile = auth_client.post(
        "/api/agents/curator/profiles",
        json={"name": "Custom", "soul_md": "SOUL-X", "agents_md": "AGENTS-X"},
    ).json()
    project = _create_project(auth_client)
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs",
        json={"agent": "curator", "profile_id": profile["id"]},
    ).json()["id"]
    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"
    assert captured["soul_md"] == "SOUL-X"
    assert captured["agents_md"] == "AGENTS-X"
    assert "Curso LLMs" in captured["task_input"]


def test_run_freezes_the_active_historical_profile_version(auth_client, monkeypatch):
    captured = {}

    def spy_curator(task_input, **kwargs):
        captured.update(kwargs)
        yield RunEvent(type="result", summary="# Brief")

    monkeypatch.setattr("factory_agents.agents.curator.run_curator", spy_curator)
    profile = auth_client.post(
        "/api/agents/curator/profiles",
        json={"name": "Custom", "soul_md": "SOUL-v1", "agents_md": "AGENTS-v1"},
    ).json()
    auth_client.patch(
        f"/api/agents/profiles/{profile['id']}",
        json={"soul_md": "SOUL-v2", "agents_md": "AGENTS-v2"},
    )
    activation = auth_client.post(
        f"/api/agents/profiles/{profile['id']}/versions/1/activate"
    )
    assert activation.status_code == 200

    project = _create_project(auth_client)
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs",
        json={"agent": "curator", "profile_id": profile["id"]},
    ).json()["id"]
    job = _wait_for_job(auth_client, job_id)

    assert job["status"] == "done"
    assert captured["soul_md"] == "SOUL-v1"
    assert captured["agents_md"] == "AGENTS-v1"
    assert job["review_policies"]["curator"]["profile_version"] == 1


def test_run_events_sse(auth_client, monkeypatch):
    monkeypatch.setattr("factory_agents.agents.curator.run_curator", _fake_curator)
    project = _create_project(auth_client)
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs", json={"agent": "curator"}
    ).json()["id"]
    _wait_for_job(auth_client, job_id)

    with auth_client.stream("GET", f"/api/runs/{job_id}/events") as resp:
        assert resp.status_code == 200
        body = ""
        for chunk in resp.iter_text():
            body += chunk
            if "event: done" in body:
                break
    assert "search_web" in body
    assert "event: done" in body
