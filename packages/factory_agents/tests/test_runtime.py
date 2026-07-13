from factory_agents.agents.curator import CURATOR_SPEC, render_curator_input
from factory_agents.runtime import REGISTRY, compose_system_prompt
from factory_agents.tools.research import build_research_tools


def test_registry_contains_agents():
    assert {"ideation", "curator"} <= set(REGISTRY)
    assert REGISTRY["ideation"].kind == "conversational"
    assert REGISTRY["curator"].produces == ("research_brief",)


def test_prompt_composition_order():
    prompt = compose_system_prompt(CURATOR_SPEC, soul_md="MI ALMA", agents_md="MIS REGLAS")
    base_pos = prompt.find("Curador de Contenido")
    agents_pos = prompt.find("MIS REGLAS")
    soul_pos = prompt.find("MI ALMA")
    assert -1 < base_pos < agents_pos < soul_pos


def test_prompt_composition_skips_empty_sections():
    prompt = compose_system_prompt(CURATOR_SPEC)
    assert "agents.md" not in prompt
    assert "soul.md" not in prompt


def test_render_curator_input_includes_brief_fields():
    text = render_curator_input(
        {"title": "Curso X", "topic": "T", "audience": "A", "level": "intro"},
        {"objectives": ["obj1"], "differential_angle": "ángulo único", "open_questions": []},
    )
    assert "Curso X" in text
    assert "obj1" in text
    assert "ángulo único" in text


def test_search_falls_back_to_duckduckgo(monkeypatch):
    monkeypatch.setattr(
        "factory_agents.tools.research._tavily_search", lambda *a, **k: None
    )
    called = {}

    def fake_ddg(query, max_results=6):
        called["query"] = query
        return []

    monkeypatch.setattr("factory_agents.tools.research.web_search", fake_ddg)
    search_web, fetch_url = build_research_tools(tavily_api_key="key-present")
    result = search_web.invoke({"query": "LLMs"})
    assert called["query"] == "LLMs"
    assert "sin resultados" in result


def test_search_uses_tavily_when_available(monkeypatch):
    monkeypatch.setattr(
        "factory_agents.tools.research._tavily_search",
        lambda query, key, max_results=5: "1. Resultado Tavily",
    )
    search_web, _ = build_research_tools(tavily_api_key="key")
    assert "Tavily" in search_web.invoke({"query": "x"})
