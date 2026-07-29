"""Lesson Generator: writes the full content of one lesson (deep agent + sandbox)."""

from collections.abc import Callable, Iterator

from factory_agents.contracts import CoursePlan
from factory_agents.runtime import AgentSpec, RunEvent, register, run_task_agent
from factory_agents.tools.sandbox import build_sandbox_tool

LESSONS_BASE_PROMPT = """\
Eres el Generador de Lecciones de AI Learning Factory. Escribes el contenido completo \
de UNA lección del curso, en Markdown, listo para convertirse en slides y guion docente.

Cómo trabajas:
1. Lee el encargo: plan de la lección (objetivo, key points), contexto del curso y \
extractos del research brief.
2. Desarrolla la lección con progresión clara: motivación → conceptos → ejemplos → \
recapitulación. Usa encabezados ## por sección.
3. Si la lección incluye código, intenta verificar cada ejemplo con `run_python`. \
La herramienta distingue tres resultados: verificado, fallo del ejemplo y no ejecutado \
por política/indisponibilidad. Corrige y repite los fallos. Si no pudo ejecutarse, no \
afirmes que está verificado y marca esa limitación de forma breve. Usa solo biblioteca \
estándar de Python.
4. Mantén la coherencia con el resto del curso: no expliques lo que se vio en lecciones \
anteriores (referéncialo) ni adelantes lo que llega después.

Tu respuesta FINAL debe ser únicamente el Markdown completo de la lección, empezando \
por `# <título de la lección>`. Escribe en el idioma del curso.
"""

DEFAULT_SOUL = """\
Profesor que se nota que ha dado clase: anticipa dónde se pierde la gente y lo \
desactiva con un ejemplo antes de que pase. Concreto, cero paja; cada párrafo enseña \
algo. Prefiere un buen ejemplo ejecutable a tres párrafos de teoría.
"""

DEFAULT_AGENTS_MD = """\
- Ajusta la longitud al presupuesto programático recibido para esta lección.
- Todo bloque de código debe verificarse en el sandbox cuando esté disponible. Distingue \
  explícitamente entre verificado, fallido y no ejecutado por política.
- Cierra siempre con "## Resumen" (3-5 bullets) que mapee al objetivo de la lección.
- Si citas datos del research brief, mantén las referencias [n].
"""

LESSONS_SPEC = register(
    AgentSpec(
        name="lessons",
        display_name="Generador de lecciones",
        description=(
            "Escribe el contenido completo de cada lección en Markdown, "
            "verificando los ejemplos de código en un sandbox."
        ),
        base_prompt=LESSONS_BASE_PROMPT,
        tool_names=("run_python",),
        consumes=("course_plan", "research_brief"),
        produces=("lesson_content",),
        default_soul_md=DEFAULT_SOUL,
        default_agents_md=DEFAULT_AGENTS_MD,
    )
)


def render_lesson_input(
    plan: CoursePlan,
    module_index: int,
    lesson_index: int,
    research_brief_md: str,
) -> str:
    module = plan.modules[module_index - 1]
    lesson = module.lessons[lesson_index - 1]
    siblings = "\n".join(
        f"  {mi}.{li} {les.title}" for mi, li, _m, les in plan.iter_lessons()
    )
    key_points = "\n".join(f"- {p}" for p in lesson.key_points)
    return (
        f"Curso: {plan.course_title} (nivel {plan.level}, audiencia: {plan.audience}, "
        f"idioma: {plan.language})\n\n"
        f"Estructura completa del curso:\n{siblings}\n\n"
        f"Escribe la lección {module_index}.{lesson_index} del módulo «{module.title}»:\n"
        f"- Título: {lesson.title}\n"
        f"- Objetivo: {lesson.objective}\n"
        f"- Duración estimada: {lesson.estimated_minutes} min\n"
        f"- Puntos clave a cubrir:\n{key_points}\n\n"
        f"Material de investigación (research brief):\n\n{research_brief_md[:8000]}"
    )


def run_lesson(
    task_input: str,
    *,
    model: str,
    api_key: str,
    workspace_dir: str,
    soul_md: str = "",
    agents_md: str = "",
    recursion_limit: int | None = None,
    callbacks: list | None = None,
    sandbox_cancel_requested: Callable[[], bool] | None = None,
) -> Iterator[RunEvent]:
    yield from run_task_agent(
        LESSONS_SPEC,
        task_input,
        model=model,
        api_key=api_key,
        workspace_dir=workspace_dir,
        soul_md=soul_md or DEFAULT_SOUL,
        agents_md=agents_md or DEFAULT_AGENTS_MD,
        tools=[build_sandbox_tool(cancel_requested=sandbox_cancel_requested)],
        recursion_limit=recursion_limit if recursion_limit is not None else 200,
        callbacks=callbacks,
    )
