import pytest
from factory_api.runner import _TOKENS_USED, BudgetExceeded, TrackedClient, add_tokens
from test_pipeline import _patch_all
from test_runs import _create_project
from test_workflows import _wait_for_job, _wait_for_status


def _make_eval_workflow(auth_client, max_regenerations=1, approval_after=False):
    profile = auth_client.post(
        "/api/agents/planner/profiles",
        json={
            "name": f"Planner review {max_regenerations}",
            "automatic_review_enabled": True,
            "max_automatic_regenerations": max_regenerations,
        },
    ).json()
    steps = [
        {"agent": "curator"},
        {
            "agent": "planner",
            "profile_id": profile["id"],
            "approval_after": approval_after,
        },
    ]
    return auth_client.post(
        "/api/workflows", json={"name": "Eval test", "steps": steps}
    ).json()


def test_evaluator_pass_lets_workflow_finish(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        "factory_api.runner.evaluate_stage", lambda job_id, agent, result: ("pass", "")
    )
    project = _create_project(auth_client)
    workflow = _make_eval_workflow(auth_client)
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow["id"]},
    ).json()["id"]
    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"
    summary = job["result"]["_automatic_reviews"]["2:planner"]
    assert summary["evaluations"] == 1
    assert summary["regenerations"] == 0
    assert summary["final_result"] == "pass"


def test_evaluator_revise_reruns_agent(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    calls = {"planner": 0}
    verdicts = iter([("revise", "faltan objetivos"), ("pass", "")])

    original = None
    import factory_api.runner as runner_module

    original = runner_module.run_planner_job

    def counting_planner(job_id, payload):
        calls["planner"] += 1
        if calls["planner"] > 1:
            assert payload.get("revision_feedback") == "faltan objetivos"
        return original(job_id, payload)

    monkeypatch.setitem(runner_module.HANDLERS, "planner_run", counting_planner)
    monkeypatch.setattr(
        "factory_api.runner.evaluate_stage",
        lambda job_id, agent, result: next(verdicts),
    )
    project = _create_project(auth_client)
    workflow = _make_eval_workflow(auth_client)
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow["id"]},
    ).json()["id"]
    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"
    assert calls["planner"] == 2  # initial + one revision
    plans = [
        artifact
        for artifact in auth_client.get(
            f"/api/projects/{project['id']}/artifacts"
        ).json()
        if artifact["type"] == "course_plan"
    ]
    assert len(plans) == 1
    assert plans[0]["version"] == 2
    assert len(plans[0]["versions"]) == 2


def test_evaluator_exhaustion_without_human_approval_continues(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        "factory_api.runner.evaluate_stage",
        lambda job_id, agent, result: ("revise", "sigue mal"),
    )
    project = _create_project(auth_client)
    workflow = _make_eval_workflow(auth_client, max_regenerations=0)
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow["id"]},
    ).json()["id"]

    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"
    summary = job["result"]["_automatic_reviews"]["2:planner"]
    assert summary["evaluations"] == 1
    assert summary["regenerations"] == 0
    assert summary["final_result"] == "exhausted"
    assert summary["destination"] == "continue"
    warnings = [
        event
        for event in job["events"]
        if event["type"] == "evaluation" and event["data"].get("status") == "warning"
    ]
    assert warnings


def test_evaluator_escalates_after_max_revisions(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        "factory_api.runner.evaluate_stage",
        lambda job_id, agent, result: ("revise", "sigue mal"),
    )
    project = _create_project(auth_client)
    workflow = _make_eval_workflow(
        auth_client, max_regenerations=0, approval_after=True
    )
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow["id"]},
    ).json()["id"]

    job = _wait_for_status(auth_client, job_id, ["waiting_approval", "done", "failed"])
    assert job["status"] == "waiting_approval"
    escalations = [e for e in job["events"] if e["type"] == "approval_required"]
    assert len(escalations) == 1

    # Human approves anyway → workflow finishes
    auth_client.post(f"/api/runs/{job_id}/approve", json={"approved": True})
    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"


def test_evaluator_escalation_rejected(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        "factory_api.runner.evaluate_stage",
        lambda job_id, agent, result: ("revise", "no hay manera"),
    )
    project = _create_project(auth_client)
    workflow = _make_eval_workflow(
        auth_client, max_regenerations=0, approval_after=True
    )
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow["id"]},
    ).json()["id"]
    _wait_for_status(auth_client, job_id, ["waiting_approval"])
    auth_client.post(
        f"/api/runs/{job_id}/approve", json={"approved": False, "feedback": "descartado"}
    )
    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "failed"
    assert "evaluación" in job["error"]


def test_evaluator_failure_is_fail_open(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        "factory_api.runner.evaluate_stage",
        lambda job_id, agent, result: (_ for _ in ()).throw(RuntimeError("judge down")),
    )
    project = _create_project(auth_client)
    workflow = _make_eval_workflow(auth_client, max_regenerations=5)
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow["id"]},
    ).json()["id"]

    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"
    summary = job["result"]["_automatic_reviews"]["2:planner"]
    assert summary["final_result"] == "evaluator_error"
    assert summary["regenerations"] == 0


def test_review_never_exceeds_five_regenerations(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    calls = {"planner": 0}
    import factory_api.runner as runner_module

    original = runner_module.run_planner_job

    def counting_planner(job_id, payload):
        calls["planner"] += 1
        return original(job_id, payload)

    monkeypatch.setitem(runner_module.HANDLERS, "planner_run", counting_planner)
    monkeypatch.setattr(
        "factory_api.runner.evaluate_stage",
        lambda job_id, agent, result: ("revise", "todavía no"),
    )
    project = _create_project(auth_client)
    workflow = _make_eval_workflow(auth_client, max_regenerations=5)
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow["id"]},
    ).json()["id"]

    job = _wait_for_job(auth_client, job_id)
    summary = job["result"]["_automatic_reviews"]["2:planner"]
    assert calls["planner"] == 6
    assert summary["evaluations"] == 6
    assert summary["regenerations"] == 5


def test_workflow_freezes_review_policy_from_profile(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    evaluations = {"count": 0}

    def passing_evaluator(job_id, agent, result):
        evaluations["count"] += 1
        return "pass", ""

    monkeypatch.setattr("factory_api.runner.evaluate_stage", passing_evaluator)
    profile = auth_client.post(
        "/api/agents/planner/profiles",
        json={
            "name": "Planner congelado",
            "automatic_review_enabled": True,
            "max_automatic_regenerations": 0,
        },
    ).json()
    workflow = auth_client.post(
        "/api/workflows",
        json={
            "name": "Freeze review",
            "steps": [
                {"agent": "curator", "approval_after": True},
                {"agent": "planner", "profile_id": profile["id"]},
            ],
        },
    ).json()
    project = _create_project(auth_client)
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow["id"]},
    ).json()["id"]
    job = _wait_for_status(auth_client, job_id, ["waiting_approval"])
    assert job["review_policies"]["planner"]["enabled"] is True
    assert job["review_policies"]["planner"]["profile_version"] == 1

    auth_client.patch(
        f"/api/agents/profiles/{profile['id']}",
        json={"automatic_review_enabled": False},
    )
    auth_client.post(f"/api/runs/{job_id}/approve", json={"approved": True})
    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"
    assert evaluations["count"] == 1
    assert job["review_policies"]["planner"]["enabled"] is True


def test_direct_agent_run_uses_profile_review_policy(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        "factory_api.runner.evaluate_stage",
        lambda job_id, agent, result: ("revise", "revisar fuentes"),
    )
    profile = auth_client.post(
        "/api/agents/curator/profiles",
        json={
            "name": "Curador revisado",
            "automatic_review_enabled": True,
            "max_automatic_regenerations": 0,
        },
    ).json()
    project = _create_project(auth_client)
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/agent-runs",
        json={"agent": "curator", "profile_id": profile["id"]},
    ).json()["id"]

    job = _wait_for_job(auth_client, job_id)
    assert job["status"] == "done"
    assert job["result"]["automatic_review"]["final_result"] == "exhausted"
    assert job["review_policies"]["curator"]["enabled"] is True


class _FakeUsageClient:
    class _Usage:
        prompt_tokens = 600_000
        completion_tokens = 400_000

    def __init__(self):
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(usage=self._Usage(), choices=[])


def test_budget_tracker_raises_when_exceeded(monkeypatch):
    from factory_api.config import get_settings

    real = get_settings()
    monkeypatch.setattr(
        "factory_api.runner.get_settings",
        lambda: real.model_copy(
            update={"budget_usd_per_run": 1.0, "budget_price_per_mtok_usd": 0.6}
        ),
    )
    _TOKENS_USED.pop("job-budget", None)
    client = TrackedClient(_FakeUsageClient(), "job-budget")
    client.chat.completions.create(model="m", messages=[])  # 1M tokens → $0.60
    with pytest.raises(BudgetExceeded, match="Presupuesto"):
        client.chat.completions.create(model="m", messages=[])  # 2M → $1.20 > $1


def test_add_tokens_disabled_budget(monkeypatch):
    from factory_api.config import get_settings

    real = get_settings()
    monkeypatch.setattr(
        "factory_api.runner.get_settings",
        lambda: real.model_copy(update={"budget_usd_per_run": 0.0}),
    )
    _TOKENS_USED.pop("job-nolimit", None)
    add_tokens("job-nolimit", 50_000_000)  # would be $30, but budget disabled
