from factory_agents.tools.research import build_research_tools
from factory_agents.tools.sources import (
    read_source_document,
    search_source_documents,
)

DOCUMENTS = [
    {
        "id": "source-a",
        "name": "curso.txt",
        "kind": "text",
        "size_bytes": 100,
        "text": (
            "[Página 1]\nLos embeddings representan texto como vectores.\n\n"
            "[Página 2]\nRAG combina recuperación y generación."
        ),
    }
]


def test_source_search_preserves_stable_id_and_location():
    result = search_source_documents(DOCUMENTS, "recuperación generación")
    assert "[source:source-a Página 2]" in result
    assert "RAG" in result
    assert "Página 1" in read_source_document(DOCUMENTS, "source-a", "Página 1")


def test_provided_only_curator_has_no_web_tools():
    tools = build_research_tools(
        research_mode="provided_only",
        source_documents=DOCUMENTS,
        max_source_queries=3,
    )
    names = {tool.name for tool in tools}
    assert names == {"list_sources", "search_sources", "read_source"}
