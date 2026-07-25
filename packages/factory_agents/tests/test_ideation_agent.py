import json
from types import SimpleNamespace

from factory_agents.agents.ideation import (
    HistoryItem,
    run_ideation_turn,
)


class FakeClient:
    """OpenAI-compatible stub scripted with a list of responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self._responses.pop(0)


def _response(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_call(name, args, call_id="tc1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def test_plain_text_turn():
    client = FakeClient([_response(content="Cuéntame más sobre tu idea.")])
    events = run_ideation_turn(client, "test-model", [])
    assert [e.kind for e in events] == ["text", "question"]
    assert len(events[-1].payload["options"]) >= 3
    assert client.requests[0]["tool_choice"] == "required"


def test_question_ends_turn():
    tc = _tool_call(
        "ask_user_question",
        {
            "question": "¿Qué nivel?",
            "options": [
                {"label": "Intro", "description": "Desde cero"},
                {"label": "Medio", "description": "Con base"},
                {"label": "Avanzado", "description": "Experto"},
            ],
        },
    )
    client = FakeClient([_response(content="Vamos a afinar.", tool_calls=[tc])])
    events = run_ideation_turn(client, "test-model", [])
    assert [e.kind for e in events] == ["text", "question"]
    assert len(events[1].payload["options"]) == 3


def test_brief_ends_turn():
    tc = _tool_call(
        "propose_brief",
        {
            "working_title": "Curso X",
            "topic": "Tema",
            "audience": "Devs",
            "level": "intermedio",
            "duration_spec": {
                "preset": "microvideo",
                "module_count": 1,
                "videos_per_module": 1,
                "target_minutes_per_video": 1,
            },
        },
    )
    client = FakeClient([_response(tool_calls=[tc])])
    events = run_ideation_turn(client, "test-model", [])
    assert [e.kind for e in events] == ["brief"]
    assert events[0].payload["working_title"] == "Curso X"
    assert events[0].payload["language"] == "es"  # default applied


def test_invalid_brief_retries_with_feedback():
    bad = _tool_call("propose_brief", {"topic": "sin título"})
    good = _tool_call(
        "propose_brief",
        {
            "working_title": "OK",
            "topic": "T",
            "audience": "A",
            "level": "intro",
            "duration_spec": {
                "preset": "microvideo",
                "module_count": 1,
                "videos_per_module": 1,
                "target_minutes_per_video": 1,
            },
        },
        call_id="tc2",
    )
    client = FakeClient([_response(tool_calls=[bad]), _response(tool_calls=[good])])
    events = run_ideation_turn(client, "test-model", [])
    assert [e.kind for e in events] == ["brief"]
    # The retry request carried the validation error back to the model
    second_request = client.requests[1]
    tool_msgs = [m for m in second_request["messages"] if m.get("role") == "tool"]
    assert any("Brief inválido" in m["content"] for m in tool_msgs)


def test_web_search_continues_turn(monkeypatch):
    monkeypatch.setattr(
        "factory_agents.agents.ideation.web_search",
        lambda query, max_results=5: [],
    )
    search = _tool_call("web_search", {"query": "cursos de cuántica"})
    client = FakeClient(
        [
            _response(tool_calls=[search]),
            _response(content="He mirado qué existe; hay hueco para tu enfoque."),
        ]
    )
    events = run_ideation_turn(client, "test-model", [])
    assert [e.kind for e in events] == ["search", "text", "question"]
    assert events[0].payload["query"] == "cursos de cuántica"


def test_history_rendering_includes_past_questions():
    history = [
        HistoryItem(role="user", kind="text", content="quiero un curso de RAG"),
        HistoryItem(
            role="assistant",
            kind="question",
            content="¿Audiencia?",
            payload={"options": [{"label": "Devs", "description": ""}]},
        ),
        HistoryItem(role="user", kind="answer", content="Devs"),
    ]
    client = FakeClient([_response(content="Perfecto.")])
    run_ideation_turn(client, "test-model", history)
    messages = client.requests[0]["messages"]
    assert messages[0]["role"] == "system"
    assert "curso de RAG" in messages[1]["content"]
    assert "¿Audiencia?" in messages[2]["content"]
    assert messages[3] == {"role": "user", "content": "Devs"}
