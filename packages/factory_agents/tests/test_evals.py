import json
from types import SimpleNamespace

from factory_agents.evals import RUBRICS, Evaluation, run_evaluator


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        message = SimpleNamespace(content=self._responses.pop(0), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_rubrics_cover_core_artifacts():
    assert {"course_plan", "lesson_content", "slide_deck"} <= set(RUBRICS)


def test_evaluator_parses_verdict():
    client = FakeClient(
        [json.dumps({"verdict": "revise", "score": 4, "feedback": "faltan objetivos"})]
    )
    ev = run_evaluator(client, "m", "course_plan", "# Plan…")
    assert isinstance(ev, Evaluation)
    assert ev.verdict == "revise"
    assert "objetivos" in ev.feedback
    # The rubric was included in the judge input
    assert "Progresión" in client.requests[0]["messages"][1]["content"]


def test_evaluator_unknown_type_passes():
    client = FakeClient([])
    ev = run_evaluator(client, "m", "video", "binario")
    assert ev.verdict == "pass"
    assert client.requests == []


def test_evaluator_broken_judge_fails_open():
    client = FakeClient(["no json", "sigue sin ser json"])
    ev = run_evaluator(client, "m", "slide_deck", "---\nmarp: true\n---")
    assert ev.verdict == "pass"
    assert "no disponible" in ev.feedback
