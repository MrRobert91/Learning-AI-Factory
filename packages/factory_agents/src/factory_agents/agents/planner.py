"""Course Designer: turns a research brief into a structured CoursePlan."""

import json
import re

from pydantic import ValidationError

from factory_agents.contracts import CoursePlan
from factory_agents.runtime import AgentSpec, compose_system_prompt, register

PLANNER_BASE_PROMPT = """\
Eres el Diseñador de Curso de AI Learning Factory. A partir de un research brief y \
los parámetros del proyecto, diseñas la estructura completa del curso: módulos, \
lecciones (cada una pensada como un vídeo o unidad autocontenida), objetivos de \
aprendizaje y duraciones estimadas.

Principios:
- Progresión pedagógica: de fundamentos a aplicación; cada lección se apoya solo en \
lo ya visto o en los prerequisitos declarados.
- Cada lección tiene UN objetivo claro y evaluable ("el estudiante sabrá X").
- Los key_points de una lección son el esqueleto real de su contenido, no generalidades.
- Respeta el nivel y la audiencia: no añadas módulos de relleno ni omitas pasos que \
la audiencia no puede saltarse.

Responde ÚNICAMENTE con un JSON válido que cumpla exactamente este esquema \
(sin comentarios, sin markdown, sin texto adicional):

{schema}
"""

DEFAULT_SOUL = """\
Arquitecto pedagógico: piensa primero en el viaje del estudiante y después en el \
temario. Prefiere cursos compactos que se terminan a enciclopedias que se abandonan. \
Cada lección debe justificar su existencia con el objetivo que desbloquea.
"""

DEFAULT_AGENTS_MD = """\
- Entre 2 y 5 módulos; entre 2 y 5 lecciones por módulo.
- Lecciones de 5 a 20 minutos (formato vídeo).
- Los títulos de lección deben funcionar como títulos de vídeo de YouTube.
- El idioma del plan es el idioma del curso.
"""

PLANNER_SPEC = register(
    AgentSpec(
        name="planner",
        display_name="Diseñador de curso",
        description=(
            "Diseña la estructura del curso: módulos, lecciones, objetivos "
            "de aprendizaje y duraciones, a partir del research brief."
        ),
        base_prompt=PLANNER_BASE_PROMPT,
        consumes=("research_brief",),
        produces=("course_plan",),
        default_soul_md=DEFAULT_SOUL,
        default_agents_md=DEFAULT_AGENTS_MD,
    )
)

MAX_ATTEMPTS = 3


def extract_json(text: str) -> dict:
    """Extract the first JSON object from a model response."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("La respuesta no contiene JSON")
        candidate = text[start : end + 1]
    return json.loads(candidate)


def render_planner_input(project: dict, research_brief_md: str) -> str:
    return (
        f"Parámetros del proyecto:\n"
        f"- Título: {project.get('title', '')}\n"
        f"- Audiencia: {project.get('audience', '')}\n"
        f"- Nivel: {project.get('level', '')}\n"
        f"- Idioma: {project.get('language', 'es')}\n"
        f"- Estilo: {project.get('style', '')}\n\n"
        f"Research brief:\n\n{research_brief_md}"
    )


def run_planner(
    task_input: str,
    *,
    client,
    model: str,
    soul_md: str = "",
    agents_md: str = "",
) -> CoursePlan:
    """One-shot structured generation with validation-driven retries."""
    schema = json.dumps(CoursePlan.model_json_schema(), ensure_ascii=False, indent=2)
    spec_prompt = compose_system_prompt(
        PLANNER_SPEC, soul_md or DEFAULT_SOUL, agents_md or DEFAULT_AGENTS_MD
    ).replace("{schema}", schema)

    messages = [
        {"role": "system", "content": spec_prompt},
        {"role": "user", "content": task_input},
    ]
    last_error: Exception | None = None
    for _ in range(MAX_ATTEMPTS):
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=0.4
        )
        text = response.choices[0].message.content or ""
        try:
            return CoursePlan.model_validate(extract_json(text))
        except (ValueError, ValidationError) as exc:
            last_error = exc
            messages.append({"role": "assistant", "content": text})
            messages.append(
                {
                    "role": "user",
                    "content": f"El JSON no es válido ({exc}). Devuelve solo el JSON corregido.",
                }
            )
    raise RuntimeError(f"El diseñador no produjo un plan válido: {last_error}")
