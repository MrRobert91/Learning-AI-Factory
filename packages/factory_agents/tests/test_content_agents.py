import json
from types import SimpleNamespace

import pytest
from factory_agents.agents.planner import extract_json, run_planner
from factory_agents.agents.slides import clean_marp_output, run_slides
from factory_agents.contracts import CoursePlan
from factory_agents.tools.sandbox import run_python_snippet


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        content = self._responses.pop(0)
        message = SimpleNamespace(content=content, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


VALID_PLAN = json.dumps(
    {
        "course_title": "Curso X",
        "language": "es",
        "modules": [
            {
                "title": "M1",
                "lessons": [{"title": "L1", "objective": "O1", "key_points": ["p1"]}],
            }
        ],
    }
)


def test_extract_json_from_fenced_block():
    text = f"Aquí tienes:\n```json\n{VALID_PLAN}\n```"
    assert extract_json(text)["course_title"] == "Curso X"


def test_planner_returns_valid_plan():
    client = FakeClient([VALID_PLAN])
    plan = run_planner("investiga X", client=client, model="m")
    assert isinstance(plan, CoursePlan)
    assert plan.modules[0].lessons[0].title == "L1"
    # Schema embedded in the system prompt
    assert "course_title" in client.requests[0]["messages"][0]["content"]


def test_planner_retries_on_invalid_json():
    client = FakeClient(["esto no es json", VALID_PLAN])
    plan = run_planner("investiga X", client=client, model="m")
    assert plan.course_title == "Curso X"
    retry_msg = client.requests[1]["messages"][-1]
    assert retry_msg["role"] == "user"
    assert "JSON" in retry_msg["content"]


def test_planner_gives_up_after_attempts():
    client = FakeClient(["nada", "tampoco", "menos"])
    with pytest.raises(RuntimeError, match="plan válido"):
        run_planner("x", client=client, model="m")


def test_slides_cleans_fences_and_keeps_frontmatter():
    deck = "---\nmarp: true\ntheme: default\npaginate: true\n---\n\n# Hola\n"
    client = FakeClient([f"```markdown\n{deck}\n```"])
    result = run_slides("lección", client=client, model="m")
    assert result.startswith("---\nmarp: true")
    assert "```markdown" not in result


def test_slides_adds_frontmatter_when_missing():
    client = FakeClient(["# Solo contenido\n"])
    result = run_slides("lección", client=client, model="m")
    assert result.startswith("---\nmarp: true")


def test_slides_enforces_vertical_canvas():
    client = FakeClient(["# Contenido vertical\n"])
    result = run_slides("lección", client=client, model="m", orientation="vertical")
    assert "size: 1080px 1920px" in result


def test_clean_marp_output_plain():
    assert clean_marp_output("# Hola") == "# Hola\n"


def test_sandbox_runs_code():
    assert run_python_snippet("print(2 + 2)").strip() == "4"


def test_sandbox_captures_errors():
    out = run_python_snippet("raise ValueError('boom')")
    assert "exit code" in out
    assert "boom" in out


def test_sandbox_times_out():
    out = run_python_snippet("while True: pass")
    assert "cancelado" in out or "límite" in out
