import json
from pathlib import Path

import pytest
from factory_agents.contracts import CoursePlan
from factory_agents.contracts.agent_io import (
    AGENT_CONTRACTS,
    AGENT_INPUTS,
    AGENT_OUTPUTS,
)
from factory_agents.runtime import RunEvent
from factory_agents.tools.slide_layout import SlideOverflowError
from factory_api.artifact_versions import add_artifact_version
from factory_api.db import SessionLocal
from factory_api.models import Artifact, Job
from factory_api.runner import (
    _latest_artifact_content,
    _restore_previous_output_selections,
    _save_artifact,
)
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
    # Review-enabled profile tests can override the evaluator deterministically.
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
    response = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs", json={"agent": "planner"}
    )
    assert response.status_code == 409
    assert "research_brief" in response.json()["detail"]


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
    assert plan_artifact["metadata"]["duration_spec"]["total_videos"] == 2

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
    assert deck["metadata"]["layout_validation"]["schema_version"] == 1
    assert "factory-safe-area:start" in deck["content"]

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


def test_slide_layout_failure_prevents_runner_artifact_publication(monkeypatch):
    def fail_layout(*_args, **_kwargs):
        raise SlideOverflowError(2, "código")

    monkeypatch.setattr(
        "factory_agents.tools.slide_layout.prepare_slide_layout", fail_layout
    )
    with pytest.raises(SlideOverflowError, match="slide 2.*código"):
        _save_artifact(
            "layout-failure-job",
            "layout-failure-project",
            "slide_deck",
            "Slides — inválidas",
            "---\nmarp: true\n---\n\n# No publicar\n",
            metadata={"orientation": "horizontal"},
        )
    with SessionLocal() as db:
        assert (
            db.query(Artifact)
            .filter(Artifact.project_id == "layout-failure-project")
            .count()
            == 0
        )


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


def test_agent_contract_matrix_is_canonical():
    assert AGENT_INPUTS["slides"] == ("course_plan", "lesson_content")
    assert AGENT_OUTPUTS["audio"] == ("audio", "subtitles")
    assert AGENT_INPUTS["video"] == ("slide_deck", "audio")
    assert AGENT_OUTPUTS["video"] == ("video",)
    web_contracts = json.loads(
        Path("apps/web/src/lib/agent_io.generated.json").read_text(encoding="utf-8")
    )
    assert web_contracts == AGENT_CONTRACTS


def test_contextual_run_revalidates_and_freezes_selected_inputs(
    auth_client,
    monkeypatch,
):
    _patch_all(monkeypatch)
    project = _create_project(auth_client)
    first = auth_client.post(
        f"/api/projects/{project['id']}/artifacts",
        files={"file": ("brief-1.md", b"# Brief 1", "text/markdown")},
        data={"type": "research_brief", "title": "Brief"},
    ).json()
    second = auth_client.post(
        f"/api/projects/{project['id']}/artifacts",
        files={"file": ("brief-2.md", b"# Brief 2", "text/markdown")},
        data={"type": "research_brief", "title": "Brief"},
    ).json()

    stale = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs",
        json={
            "agent": "planner",
            "expected_input_artifact_ids": {"research_brief": [first["id"]]},
            "request_id": "stale-selection",
            "trigger": "artifact_card",
        },
    )
    assert stale.status_code == 409
    assert "selección de artefactos cambió" in stale.json()["detail"]

    created = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs",
        json={
            "agent": "planner",
            "expected_input_artifact_ids": {"research_brief": [second["id"]]},
            "request_id": "planner-from-card",
            "trigger": "artifact_card",
        },
    )
    assert created.status_code == 201
    job_id = created.json()["id"]
    with SessionLocal() as db:
        payload = json.loads(db.get(Job, job_id).payload_json)
    assert payload["input_artifact_ids"] == {"research_brief": [second["id"]]}
    assert payload["previous_output_artifact_ids"] == {"course_plan": []}
    assert _latest_artifact_content(payload, "research_brief") == (
        second["id"],
        "# Brief 2",
    )
    assert _wait_for_job(auth_client, job_id)["status"] == "done"

    repeated = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs",
        json={
            "agent": "planner",
            "expected_input_artifact_ids": {"research_brief": [second["id"]]},
            "request_id": "planner-from-card",
            "trigger": "artifact_card",
        },
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == job_id


def test_contextual_run_rejects_an_active_project_job(auth_client):
    project = _create_project(auth_client)
    with SessionLocal() as db:
        active = Job(kind="curator_run", project_id=project["id"], status="paused")
        db.add(active)
        db.commit()
        active_id = active.id

    response = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs",
        json={"agent": "curator", "request_id": "blocked-by-active"},
    )
    assert response.status_code == 409
    assert active_id[:8] in response.json()["detail"]


def test_failed_contextual_regeneration_restores_previous_selection(auth_client):
    project = _create_project(auth_client)
    with SessionLocal() as db:
        previous = add_artifact_version(
            db,
            project_id=project["id"],
            type_="course_plan",
            format_="json",
            title="Plan",
            path="artifacts/previous.json",
        )
        db.flush()
        job = Job(
            kind="planner_run",
            project_id=project["id"],
            payload_json=json.dumps(
                {
                    "project_id": project["id"],
                    "previous_output_artifact_ids": {
                        "course_plan": [previous.id],
                    },
                }
            ),
        )
        db.add(job)
        db.flush()
        replacement = add_artifact_version(
            db,
            project_id=project["id"],
            type_="course_plan",
            format_="json",
            title="Plan",
            path="artifacts/replacement.json",
            created_by_job_id=job.id,
        )
        db.commit()
        previous_id = previous.id
        replacement_id = replacement.id
        job_id = job.id

    _restore_previous_output_selections(job_id)
    with SessionLocal() as db:
        assert db.get(Artifact, previous_id).is_selected is True
        assert db.get(Artifact, replacement_id).is_selected is False


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


def test_artifact_versions_can_be_selected_and_deleted(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    project = _create_project(auth_client)

    ids = []
    for index, content in enumerate((b"# Version uno", b"# Version dos"), start=1):
        response = auth_client.post(
            f"/api/projects/{project['id']}/artifacts",
            files={"file": ("brief.md", content, "text/markdown")},
            data={"type": "research_brief", "title": f"Brief con título {index}"},
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])

    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    assert len(artifacts) == 1
    assert artifacts[0]["id"] == ids[1]
    assert artifacts[0]["version"] == 2
    assert len(artifacts[0]["versions"]) == 2

    selected = auth_client.post(f"/api/artifacts/{ids[0]}/select").json()
    assert selected["is_selected"] is True
    assert selected["version"] == 1
    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    assert artifacts[0]["id"] == ids[0]

    seen = {}

    def capture_planner(task_input, **kwargs):
        seen["task_input"] = task_input
        return FAKE_PLAN

    monkeypatch.setattr("factory_agents.agents.planner.run_planner", capture_planner)
    assert _run_agent(auth_client, project["id"], "planner")["status"] == "done"
    assert "Version uno" in seen["task_input"]
    assert "Version dos" not in seen["task_input"]

    assert auth_client.delete(f"/api/artifacts/{ids[0]}").status_code == 204
    artifacts = auth_client.get(f"/api/projects/{project['id']}/artifacts").json()
    brief = next(artifact for artifact in artifacts if artifact["type"] == "research_brief")
    assert brief["id"] == ids[1]
    assert brief["is_selected"] is True
