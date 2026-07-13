"""Lightweight web search (DuckDuckGo, no API key)."""

from dataclasses import dataclass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


def web_search(query: str, max_results: int = 5) -> list[SearchResult]:
    from ddgs import DDGS

    results: list[SearchResult] = []
    try:
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=max_results):
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("href", ""),
                        snippet=item.get("body", ""),
                    )
                )
    except Exception:
        # Search is best-effort: the ideation agent must keep working
        # (and say so) when DuckDuckGo rate-limits or the network fails.
        return []
    return results


def format_results(results: list[SearchResult]) -> str:
    if not results:
        return "(sin resultados: la búsqueda no está disponible ahora mismo)"
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.title}\n   {r.url}\n   {r.snippet}")
    return "\n".join(lines)
