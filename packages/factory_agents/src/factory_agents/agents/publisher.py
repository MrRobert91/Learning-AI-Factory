"""YouTube Publisher: prepares metadata, chapters and thumbnail copy.

The agent only PREPARES the publication package; the actual upload always
requires an explicit human action in the UI (hard guardrail).
"""

import json

from pydantic import ValidationError

from factory_agents.agents.planner import extract_json
from factory_agents.contracts.publication import PublicationPackage
from factory_agents.runtime import AgentSpec, compose_system_prompt, register

PUBLISHER_BASE_PROMPT = """\
Eres el Publicador de AI Learning Factory. Preparas la publicación en YouTube del \
vídeo de una lección: título, descripción, tags, capítulos y el texto de la miniatura.

Criterios:
- Título: claro y buscable, promete el resultado de aprendizaje, sin clickbait vacío. \
Máximo 100 caracteres; los primeros 60 deben funcionar solos.
- Descripción: 2-3 frases de gancho con keywords naturales, luego la sección \
"Capítulos:" con los timestamps recibidos, luego qué aprenderá el espectador y \
enlaces/recursos del curso si los hay.
- Capítulos: usa EXACTAMENTE los timestamps proporcionados (no los inventes); dales \
títulos cortos y descriptivos. El primero siempre es 00:00.
- Tags: 8-15, mezcla de específicos y de categoría.
- Miniatura: thumbnail_title de máximo 5-6 palabras, legible a tamaño pequeño; \
thumbnail_subtitle opcional.

Responde ÚNICAMENTE con un JSON válido según este esquema (sin markdown):

{schema}
"""

DEFAULT_SOUL = """\
Editor de canal con criterio: optimiza para el clic honesto — el título promete \
exactamente lo que el vídeo cumple. Piensa en cómo se ve el título+miniatura en un \
feed lleno de competencia, y en qué buscaría en YouTube alguien que necesita esta lección.
"""

DEFAULT_AGENTS_MD = """\
- Idioma de todos los metadatos: el del curso.
- No uses mayúsculas completas ni más de un signo de exclamación en el título.
- La descripción no debe superar ~2000 caracteres.
"""

PUBLISHER_SPEC = register(
    AgentSpec(
        name="publisher",
        display_name="Publicador YouTube",
        description=(
            "Prepara título, descripción, tags, capítulos y miniatura del vídeo. "
            "La subida a YouTube siempre requiere tu aprobación explícita."
        ),
        base_prompt=PUBLISHER_BASE_PROMPT,
        consumes=("video", "subtitles", "teaching_script"),
        produces=("publication_package",),
        default_soul_md=DEFAULT_SOUL,
        default_agents_md=DEFAULT_AGENTS_MD,
    )
)

MAX_ATTEMPTS = 3


def render_publisher_input(
    lesson_label: str,
    course_title: str,
    chapter_timestamps: list[str],
    script_excerpt: str,
    language: str,
) -> str:
    timestamps = "\n".join(chapter_timestamps) or "(vídeo sin capítulos calculados)"
    return (
        f"Curso: {course_title}\n"
        f"Lección: {lesson_label}\n"
        f"Idioma: {language}\n\n"
        f"Timestamps de inicio de cada sección (para los capítulos):\n{timestamps}\n\n"
        f"Guion de la lección (para entender el contenido):\n\n{script_excerpt[:6000]}"
    )


def run_publisher(
    task_input: str,
    *,
    client,
    model: str,
    soul_md: str = "",
    agents_md: str = "",
) -> PublicationPackage:
    schema = json.dumps(
        PublicationPackage.model_json_schema(), ensure_ascii=False, indent=2
    )
    prompt = compose_system_prompt(
        PUBLISHER_SPEC, soul_md or DEFAULT_SOUL, agents_md or DEFAULT_AGENTS_MD
    ).replace("{schema}", schema)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": task_input},
    ]
    last_error: Exception | None = None
    for _ in range(MAX_ATTEMPTS):
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=0.5
        )
        text = response.choices[0].message.content or ""
        try:
            return PublicationPackage.model_validate(extract_json(text))
        except (ValueError, ValidationError) as exc:
            last_error = exc
            messages.append({"role": "assistant", "content": text})
            messages.append(
                {
                    "role": "user",
                    "content": f"El JSON no es válido ({exc}). Devuelve solo el JSON corregido.",
                }
            )
    raise RuntimeError(f"El publicador no produjo un paquete válido: {last_error}")
