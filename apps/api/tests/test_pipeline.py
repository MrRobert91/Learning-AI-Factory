import json

from factory_agents.contracts import CoursePlan
from factory_agents.runtime import RunEvent
from test_runs import _create_project, _fake_curator, _wait_for_job

FAKE_PLAN = CoursePlan(
    course_title="Curso LLMs",
    summary="Intro a LLMs",
    audience="devs",
    level="intro",
    language="es",
    modules=[
        {
            "title": "Fundamentos",
            "summary": "",
            "lessons": [
                {"title": "Qué es un LLM", "objective": "Entenderlo", "key_points": ["tokens"]},
                {"title": "Prompting", "objective": "Escribir prompts", "key_points": ["few-shot"]},
            ],
        }
    ],
)


def _fake_planner(task_input, **kwargs):
    return FAKE_PLAN


def _fake_lesson(task_input, **kwargs):
    yield RunEvent(
        type="tool_call", summary="run_python(code=print(1))", data={"tool": "run_python"}
    )
    yield RunEvent(type="result", summary="# Lección\n\nContenido…\n\n## Resumen\n- ok")


def _fake_slides(task_input, **kwargs):
    return (
        "---\nmarp: true\ntheme: default\npaginate: true\n---\n\n"
        "# Portada\n\n---\n\n## Resumen\n"
    )


def _patch_all(monkeypatch):
    monkeypatch.setattr("factory_agents.agents.curator.run_curator", _fake_curator)
    monkeypatch.setattr("factory_agents.agents.planner.run_planner", _fake_planner)
    monkeypatch.setattr("factory_agents.agents.lessons.run_lesson", _fake_lesson)
    monkeypatch.setattr("factory_agents.agents.slides.run_slides", _fake_slides)
    monkeypatch.setattr("factory_agents.llm.get_llm_client", lambda key: object())
    # Templates carry evaluate=true on core steps; default to passing judge.
    monkeypatch.setattr(
        "factory_api.runner.evaluate_stage", lambda job_id, agent, result: ("pass", "")
    )


def _run_agent(auth_client, project_id, agent):
    job_id = auth_client.post(
        f"/api/projects/{project_id}/agent-runs", json={"agent": agent}
    ).json()["id"]
    return _wait_for_job(auth_client, job_id)


def test_planner_requires_research_brief(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    project = _create_project(auth_client)
    job = _run_agent(auth_client, project["id"], "planner")
    assert job["status"] == "failed"
    assert "research_brief" in job["error"]


def test_stage_by_stage_chain(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    project = _create_project(auth_client)

    assert _run_agent(auth_client, project["id"], "curator")["status"] == "done"

    planner_job = _run_agent(auth_client, project["id"], "planner")
    assert planner_job["status"] == "done"
    plan_artifact = auth_client.get(
        f"/api/artifacts/{planner_job['result']['artifact_id']}"
    ).json()
    assert plan_artifact["type"] == "course_plan"
    assert json.loads(plan_artifact["content"])["course_title"] == "Curso LLMs"

    lessons_job = _run_agent(auth_client, project["id"], "lessons")
    assert lessons_job["status"] == "done"
    assert len(lessons_job["result"]["artifact_ids"]) == 2

    slides_job = _run_agent(auth_client, project["id"], "slides")
    assert slides_job["status"] == "done"
    assert len(slides_job["result"]["artifact_ids"]) == 2
    deck = auth_client.get(
        f"/api/artifacts/{slides_job['result']['artifact_ids'][0]}"
    ).json()
    assert deck["type"] == "slide_deck"
    assert deck["content"].startswith("---\nmarp: true")

    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    types = sorted({a["type"] for a in artifacts})
    assert types == ["course_plan", "lesson_content", "research_brief", "slide_deck"]


def test_slide_decks_are_stored_in_distinct_files(auth_client, monkeypatch):
    """Regression: each lesson's deck must have its own file, otherwise every
    slide_deck artifact points at the last lesson's deck and only the last one
    is downloadable."""
    _patch_all(monkeypatch)

    counter = {"n": 0}

    def _distinct_slides(task_input, **kwargs):
        counter["n"] += 1
        return f"---\nmarp: true\ntheme: default\npaginate: true\n---\n\n# Deck {counter['n']}\n"

    monkeypatch.setattr("factory_agents.agents.slides.run_slides", _distinct_slides)

    project = _create_project(auth_client)
    assert _run_agent(auth_client, project["id"], "curator")["status"] == "done"
    assert _run_agent(auth_client, project["id"], "planner")["status"] == "done"
    assert _run_agent(auth_client, project["id"], "lessons")["status"] == "done"

    slides_job = _run_agent(auth_client, project["id"], "slides")
    ids = slides_job["result"]["artifact_ids"]
    assert len(ids) == 2

    downloads = [auth_client.get(f"/api/artifacts/{aid}/download").text for aid in ids]
    assert downloads[0] != downloads[1]
    assert "# Deck 1" in downloads[0]
    assert "# Deck 2" in downloads[1]


def test_full_pipeline_run(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    project = _create_project(auth_client)
    job = _run_agent(auth_client, project["id"], "pipeline")
    assert job["status"] == "done"
    assert set(job["result"].keys()) == {"curator", "planner", "lessons", "slides"}
    stages = [e["summary"] for e in job["events"] if e["type"] == "stage"]
    assert any("Curador" in s for s in stages)
    assert any("slides" in s.lower() for s in stages)
    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    assert len([a for a in artifacts if a["type"] == "slide_deck"]) == 2


def test_unknown_agent_rejected(auth_client):
    project = _create_project(auth_client)
    resp = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs", json={"agent": "nope"}
    )
    assert resp.status_code == 422


def test_upload_external_artifact(auth_client):
    project = _create_project(auth_client)
    resp = auth_client.post(
        f"/api/projects/{project['id']}/artifacts",
        files={"file": ("mis-slides.md", b"---\nmarp: true\n---\n\n# Mias", "text/markdown")},
        data={"type": "slide_deck", "title": "Mis slides"},
    )
    assert resp.status_code == 201
    artifact = resp.json()
    assert artifact["type"] == "slide_deck"
    full = auth_client.get(f"/api/artifacts/{artifact['id']}").json()
    assert "# Mias" in full["content"]

    resp = auth_client.post(
        f"/api/projects/{project['id']}/artifacts",
        files={"file": ("x.bin", b"\x00", "application/octet-stream")},
        data={"type": "video"},
    )
    assert resp.status_code == 422
