"""Project memory: an OpenWiki-Brains-style wiki maintained by a librarian.

After each successful agent job, a cheap LLM pass ("the librarian")
consolidates what was produced into a small set of wiki pages (decisions,
glossary, style...). Later agents read those pages for cross-lesson
coherence. Pages are plain Markdown persisted by the API layer; wikis are
small, so retrieval is whole-wiki injection (no vector index needed yet).
"""

import json

from pydantic import BaseModel, Field, ValidationError

from factory_agents.agents.planner import extract_json

DEFAULT_PAGES = ("decisiones", "glosario", "estilo")

LIBRARIAN_PROMPT = """\
Eres el Bibliotecario de AI Learning Factory. Mantienes la wiki de memoria de un \
proyecto de curso: páginas Markdown breves que los demás agentes leen para mantener \
la coherencia entre lecciones.

Páginas habituales (crea otras solo si aportan de verdad):
- decisiones: decisiones tomadas sobre el curso (alcance, enfoque, qué se descartó y por qué)
- glosario: términos del curso con la definición/traducción EXACTA que se está usando
- estilo: convenciones de tono, formato y ejemplos acordadas

Recibes las páginas actuales y un resumen de lo último que ha producido un agente. \
Devuelve SOLO las páginas que cambien (o nuevas), completas y reescritas. Sé \
selectivo: la wiki es memoria destilada, no un registro de todo. Máximo ~300 \
palabras por página. Si nada merece actualizarse, devuelve una lista vacía.

Responde ÚNICAMENTE con JSON válido:
{"pages": [{"slug": "glosario", "title": "Glosario", "content_md": "..."}]}
"""


class WikiPageUpdate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str
    content_md: str


class LibrarianResult(BaseModel):
    pages: list[WikiPageUpdate] = Field(default_factory=list)


def render_wiki_for_prompt(pages: list[dict], max_chars: int = 4000) -> str:
    """Render wiki pages as a prompt section for other agents."""
    if not pages:
        return ""
    parts = []
    for page in pages:
        parts.append(f"### {page.get('title', page.get('slug', ''))}\n{page.get('content_md', '')}")
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…(memoria truncada)"
    return "# Memoria del proyecto (wiki)\n\n" + text


def run_librarian(
    client,
    model: str,
    current_pages: list[dict],
    event_summary: str,
    artifact_excerpt: str,
) -> list[WikiPageUpdate]:
    """One consolidation pass. Returns the pages to upsert (possibly none)."""
    pages_json = json.dumps(
        [
            {
                "slug": p.get("slug"),
                "title": p.get("title"),
                "content_md": p.get("content_md", "")[:2000],
            }
            for p in current_pages
        ],
        ensure_ascii=False,
    )
    user_input = (
        f"Páginas actuales de la wiki:\n{pages_json}\n\n"
        f"Qué acaba de pasar: {event_summary}\n\n"
        f"Extracto de lo producido:\n{artifact_excerpt[:5000]}"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": LIBRARIAN_PROMPT},
            {"role": "user", "content": user_input},
        ],
        temperature=0.2,
    )
    text = response.choices[0].message.content or ""
    try:
        return LibrarianResult.model_validate(extract_json(text)).pages
    except (ValueError, ValidationError):
        # Memory consolidation is best-effort: never break the main job.
        return []
