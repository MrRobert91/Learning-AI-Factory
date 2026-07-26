"""Research tools for the curator agent: web search and URL fetching.

Search uses Tavily when an API key is configured and falls back to
DuckDuckGo otherwise (or when Tavily fails).
"""

import httpx
from langchain_core.tools import tool

from factory_agents.tools.web_search import format_results, web_search

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_PAGE_CHARS = 12000


def _tavily_search(query: str, api_key: str, max_results: int = 5) -> str | None:
    try:
        resp = httpx.post(
            TAVILY_SEARCH_URL,
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "include_answer": False,
            },
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception:
        return None
    if not results:
        return None
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r.get('title', '')}\n   {r.get('url', '')}\n   {r.get('content', '')}"
        )
    return "\n".join(lines)


def extract_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def build_research_tools(tavily_api_key: str = "", max_searches: int | None = None):
    """Build the search + fetch tools with provider config baked in."""
    searches_used = 0

    @tool
    def search_web(query: str) -> str:
        """Busca en la web. Devuelve títulos, URLs y extractos de los resultados."""
        nonlocal searches_used
        if max_searches is not None and searches_used >= max_searches:
            return (
                f"(límite de {max_searches} búsquedas alcanzado; "
                "redacta con las fuentes ya consultadas)"
            )
        searches_used += 1
        if tavily_api_key:
            result = _tavily_search(query, tavily_api_key)
            if result is not None:
                return result
        return format_results(web_search(query, max_results=6))

    @tool
    def fetch_url(url: str) -> str:
        """Descarga una página web y devuelve su contenido como texto plano."""
        try:
            resp = httpx.get(
                url,
                timeout=25,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (AI Learning Factory research agent)"},
            )
            resp.raise_for_status()
        except Exception as exc:
            return f"(no se pudo descargar {url}: {exc})"
        content_type = resp.headers.get("content-type", "")
        if "html" in content_type:
            text = extract_text(resp.text)
        else:
            text = resp.text
        if len(text) > MAX_PAGE_CHARS:
            text = text[:MAX_PAGE_CHARS] + "\n…(truncado)"
        return text

    return [search_web, fetch_url]
