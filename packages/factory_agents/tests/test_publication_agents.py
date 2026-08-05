import json
from types import SimpleNamespace

from factory_agents.agents.publisher import apply_recurrent_content, run_publisher
from factory_agents.contracts.publication import PublicationPackage
from factory_agents.memory import render_wiki_for_prompt, run_librarian


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        message = SimpleNamespace(content=self._responses.pop(0), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_publisher_parses_package():
    payload = json.dumps(
        {
            "video_title": "Qué es un LLM",
            "description": "Aprende…\n\nCapítulos:\n00:00 Intro",
            "tags": ["llm"],
            "chapters": ["00:00 Intro"],
            "thumbnail_title": "¿Qué es un LLM?",
        }
    )
    client = FakeClient([payload])
    package = run_publisher("input", client=client, model="m")
    assert isinstance(package, PublicationPackage)
    assert package.video_title.startswith("Qué es")
    # Schema is embedded in the system prompt
    assert "video_title" in client.requests[0]["messages"][0]["content"]


def test_recurrent_content_is_appended_once():
    package = PublicationPackage(
        video_title="Curso",
        description="Descripción generada",
        tags=["ia"],
        chapters=["00:00 Inicio"],
        thumbnail_title="Curso completo",
    )
    updated = apply_recurrent_content(
        package,
        "Suscríbete al canal.",
        "Web: https://example.com",
    )
    assert updated.description.endswith(
        "Suscríbete al canal.\n\nWeb: https://example.com"
    )
    assert apply_recurrent_content(
        updated,
        "Suscríbete al canal.",
        "Web: https://example.com",
    ).description == updated.description


def test_librarian_returns_page_updates():
    payload = json.dumps(
        {
            "pages": [
                {"slug": "glosario", "title": "Glosario", "content_md": "- LLM: …"}
            ]
        }
    )
    client = FakeClient([payload])
    updates = run_librarian(client, "m", [], "curator done", "extracto")
    assert len(updates) == 1
    assert updates[0].slug == "glosario"


def test_librarian_is_best_effort_on_garbage():
    client = FakeClient(["esto no es json"])
    assert run_librarian(client, "m", [], "x", "y") == []


def test_render_wiki_for_prompt():
    assert render_wiki_for_prompt([]) == ""
    text = render_wiki_for_prompt(
        [{"slug": "estilo", "title": "Estilo", "content_md": "Tono cercano."}]
    )
    assert "Memoria del proyecto" in text
    assert "Tono cercano." in text
    long = render_wiki_for_prompt(
        [{"slug": "x", "title": "X", "content_md": "a" * 9000}], max_chars=100
    )
    assert "truncada" in long
