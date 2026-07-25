"""Content Curator: researches a topic and produces a research_brief."""

from collections.abc import Iterator

from factory_agents.runtime import AgentSpec, RunEvent, register, run_task_agent
from factory_agents.tools.research import build_research_tools

CURATOR_BASE_PROMPT = """\
Eres el Curador de Contenido de AI Learning Factory. Tu misión: investigar a fondo \
el tema de un curso y producir un research brief que servirá de base a todo el \
pipeline (plan del curso, lecciones, slides, vídeo).

Método de trabajo:
1. Analiza el encargo (tema, audiencia, nivel, objetivos) y planifica la investigación.
2. Usa `search_web` para explorar el tema y `fetch_url` para leer en profundidad las \
fuentes más prometedoras. Ve guardando notas intermedias en ficheros del workspace.
3. Contrasta: prioriza fuentes primarias y actuales, señala desacuerdos entre fuentes \
y distingue hechos consolidados de afirmaciones dudosas.
4. Cíñete al alcance y nivel del encargo: investiga lo que el curso necesita, no todo \
lo que existe.

Tu respuesta FINAL debe ser el research brief completo en Markdown, con esta estructura:

# Research Brief: <tema>
## Resumen ejecutivo
## Conceptos clave (con definiciones al nivel de la audiencia)
## Estado del arte y contexto
## Estructura temática sugerida (bloques de contenido con ideas para lecciones)
## Ejemplos, analogías y casos útiles para enseñar
## Errores comunes y malentendidos de los estudiantes
## Fuentes (numeradas, con URL y una línea sobre su fiabilidad y qué aporta)
## Cuestiones abiertas o a verificar

Escribe el brief en el idioma del curso. Cita las fuentes por número en el texto.
"""

DEFAULT_SOUL = """\
Riguroso pero pragmático. Prefiere pocas fuentes buenas a muchas mediocres; ante la \
duda, la fuente primaria. No rellena huecos con generalidades: si algo no está claro, \
lo marca como cuestión abierta. Piensa siempre en el profesor que usará este material: \
cada sección debe ahorrarle trabajo, no dárselo.
"""

DEFAULT_AGENTS_MD = """\
- Ajusta búsquedas, fuentes y extensión a las restricciones estructurales del proyecto.
- Las fuentes deben incluir URL real (nunca inventes URLs) y fecha aproximada si es relevante.
- Si el tema evoluciona rápido (IA, tecnología), prioriza material de los últimos 18 meses.
"""

CURATOR_SPEC = register(
    AgentSpec(
        name="curator",
        display_name="Curador de contenido",
        description=(
            "Investiga el tema del curso en la web y produce un research brief "
            "con fuentes citadas, estructura temática y material didáctico."
        ),
        base_prompt=CURATOR_BASE_PROMPT,
        tool_names=("search_web", "fetch_url"),
        consumes=("course_idea_brief",),
        produces=("research_brief",),
        default_soul_md=DEFAULT_SOUL,
        default_agents_md=DEFAULT_AGENTS_MD,
    )
)


def render_curator_input(project: dict, brief: dict | None = None) -> str:
    """Render the task prompt from project fields and optional idea brief."""
    lines = [
        "Investiga para el siguiente curso:",
        f"- Título: {project.get('title', '')}",
        f"- Tema: {project.get('topic', '')}",
        f"- Audiencia: {project.get('audience', '')}",
        f"- Nivel: {project.get('level', '')}",
        f"- Idioma del curso: {project.get('language', 'es')}",
        f"- Estilo: {project.get('style', '')}",
    ]
    if brief:
        if brief.get("objectives"):
            lines.append("- Objetivos: " + "; ".join(brief["objectives"]))
        if brief.get("scope_outline"):
            lines.append("- Alcance orientativo: " + "; ".join(brief["scope_outline"]))
        if brief.get("differential_angle"):
            lines.append(f"- Ángulo diferencial: {brief['differential_angle']}")
        if brief.get("open_questions"):
            lines.append(
                "- Cuestiones abiertas a resolver: " + "; ".join(brief["open_questions"])
            )
    return "\n".join(lines)


def run_curator(
    task_input: str,
    *,
    model: str,
    api_key: str,
    tavily_api_key: str,
    workspace_dir: str,
    soul_md: str = "",
    agents_md: str = "",
    recursion_limit: int | None = None,
    callbacks: list | None = None,
    max_searches: int | None = None,
) -> Iterator[RunEvent]:
    tools = build_research_tools(tavily_api_key, max_searches=max_searches)
    yield from run_task_agent(
        CURATOR_SPEC,
        task_input,
        model=model,
        api_key=api_key,
        workspace_dir=workspace_dir,
        soul_md=soul_md or DEFAULT_SOUL,
        agents_md=agents_md or DEFAULT_AGENTS_MD,
        tools=tools,
        recursion_limit=recursion_limit if recursion_limit is not None else 200,
        callbacks=callbacks,
    )
