"""Voice Adapter: rewrites the teaching script for synthetic narration."""

import json

from pydantic import ValidationError

from factory_agents.agents.planner import extract_json
from factory_agents.contracts import VoiceScript
from factory_agents.runtime import AgentSpec, compose_system_prompt, register

VOICE_BASE_PROMPT = """\
Eres el Adaptador de Voz de AI Learning Factory. Conviertes el guion docente de una \
lección en un guion de narración listo para voz sintética (TTS).

Reglas de adaptación:
- Reescribe para oralidad: frases cortas, sintaxis directa, sin paréntesis largos.
- Elimina cualquier referencia visual deíctica ("como veis aquí", "esta slide"): la \
voz debe funcionar aunque el oyente no mire la pantalla en ese instante.
- Expande siglas la primera vez y escribe los símbolos como se pronuncian \
(p. ej. "->" como "produce", "==" como "es igual a") cuando se narre código.
- Mantén UN segmento por slide, en el mismo orden del guion.

Responde ÚNICAMENTE con un JSON válido con este esquema exacto (sin markdown):

{schema}
"""

DEFAULT_SOUL = """\
Locutor técnico con oído: lee en voz alta mentalmente cada frase antes de darla por \
buena. Si algo suena robótico o a texto leído, lo reescribe. El ritmo importa tanto \
como el contenido.
"""

DEFAULT_AGENTS_MD = """\
- Longitud por segmento: 40-150 palabras.
- No inventes contenido nuevo: solo adapta lo que dice el guion docente.
- Mantén el idioma del guion original.
"""

VOICE_SPEC = register(
    AgentSpec(
        name="voice",
        display_name="Adaptador de voz",
        description=(
            "Adapta el guion docente a narración para voz sintética, "
            "segmentado por slide y listo para TTS."
        ),
        base_prompt=VOICE_BASE_PROMPT,
        consumes=("teaching_script",),
        produces=("voice_script",),
        default_soul_md=DEFAULT_SOUL,
        default_agents_md=DEFAULT_AGENTS_MD,
    )
)

MAX_ATTEMPTS = 3


def render_voice_input(script_md: str, lesson_title: str, language: str) -> str:
    return (
        f"Lección: {lesson_title}\nIdioma: {language}\n\n"
        f"Guion docente a adaptar:\n\n{script_md}"
    )


def run_voice(
    task_input: str,
    *,
    client,
    model: str,
    soul_md: str = "",
    agents_md: str = "",
) -> VoiceScript:
    schema = json.dumps(VoiceScript.model_json_schema(), ensure_ascii=False, indent=2)
    prompt = compose_system_prompt(
        VOICE_SPEC, soul_md or DEFAULT_SOUL, agents_md or DEFAULT_AGENTS_MD
    ).replace("{schema}", schema)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": task_input},
    ]
    last_error: Exception | None = None
    for _ in range(MAX_ATTEMPTS):
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=0.4
        )
        text = response.choices[0].message.content or ""
        try:
            return VoiceScript.model_validate(extract_json(text))
        except (ValueError, ValidationError) as exc:
            last_error = exc
            messages.append({"role": "assistant", "content": text})
            messages.append(
                {
                    "role": "user",
                    "content": f"El JSON no es válido ({exc}). Devuelve solo el JSON corregido.",
                }
            )
    raise RuntimeError(f"El adaptador de voz no produjo un guion válido: {last_error}")
