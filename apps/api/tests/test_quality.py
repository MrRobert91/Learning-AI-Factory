import pytest
from factory_api.runner import _TOKENS_USED, BudgetExceeded, TrackedClient, add_tokens
from test_pipeline import _patch_all
from test_runs import _create_project
from test_workflows import _wait_for_job, _wait_for_status


def _make_eval_workflow(auth_client, evaluate_step="planner"):
    steps = [
        {"agent": "curator"},
        {"agent": "planner", "evaluate": evaluate_step == "planner"},
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


def test_evaluator_escalates_after_max_revisions(auth_client, monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setattr(
        "factory_api.runner.evaluate_stage",
        lambda job_id, agent, result: ("revise", "sigue mal"),
    )
    project = _create_project(auth_client)
    workflow = _make_eval_workflow(auth_client)
    job_id = auth_client.post(
        f"/api/projects/{project['id']}/workflow-runs",
        json={"workflow_id": workflow["id"]},
    ).json()["id"]

    job = _wait_for_status(auth_client, job_id, ["waiting_approval", "done", "failed"])
    assert job["status"] == "waiting_approval"
    escalations = [e for e in job["events"] if e["type"] == "approval_required"]
    assert escalations

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
    workflow = _make_eval_workflow(auth_client)
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
