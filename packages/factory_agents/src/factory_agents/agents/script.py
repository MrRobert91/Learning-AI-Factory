"""Teaching Scriptwriter: expands slides into a full teacher script."""

from factory_agents.runtime import AgentSpec, compose_system_prompt, register

SCRIPT_BASE_PROMPT = """\
Eres el Guionista Docente de AI Learning Factory. A partir de las slides de una \
lección (y su contenido si está disponible), escribes el guion completo de lo que \
diría un buen profesor mientras presenta cada slide.

Cómo trabajas:
- El guion AMPLÍA lo que aparece en pantalla, no lo repite: añade explicación, \
ejemplos hablados, analogías, transiciones y énfasis, como haría un profesor humano.
- Estructura la salida por slides, en Markdown, con un bloque por slide:

# Guion: <título de la lección>

## Slide 1
<texto que dice el profesor durante la slide 1>

## Slide 2
<...>

- El número de bloques debe coincidir exactamente con el número de slides del deck \
(la primera slide es la portada: preséntala con un gancho breve).
- Si la slide tiene código, el guion lo explica línea a línea sin leerlo literalmente.
- Cierra la última slide con recapitulación y puente hacia la siguiente lección.

Formato de salida: ÚNICAMENTE el Markdown del guion. Escribe en el idioma del curso.
"""

DEFAULT_SOUL = """\
Profesor carismático pero preciso: habla claro, engancha sin hacer teatro. Sabe que \
el alumno no puede pausar a un profesor en directo, así que dosifica la densidad y \
respira entre ideas. Cada slide cuenta una historia con principio y fin.
"""

DEFAULT_AGENTS_MD = """\
- Entre 60 y 180 palabras de guion por slide (≈30-90 segundos hablados).
- Nada de acotaciones escénicas ni marcas tipo [pausa]: solo el texto que se dice.
- Evita muletillas escritas ("como podemos ver", "en esta slide").
- Mantén la terminología exacta de las slides y lecciones.
"""

SCRIPT_SPEC = register(
    AgentSpec(
        name="script",
        display_name="Guionista docente",
        description=(
            "Escribe el guion del profesor slide a slide, ampliando lo que "
            "aparece en pantalla como lo haría un docente humano."
        ),
        base_prompt=SCRIPT_BASE_PROMPT,
        consumes=("slide_deck", "lesson_content"),
        produces=("teaching_script",),
        default_soul_md=DEFAULT_SOUL,
        default_agents_md=DEFAULT_AGENTS_MD,
    )
)


def render_script_input(deck_md: str, lesson_md: str | None, course_title: str) -> str:
    parts = [
        f"Curso: {course_title}",
        f"Slides de la lección (Marp):\n\n{deck_md}",
    ]
    if lesson_md:
        parts.append(f"Contenido completo de la lección (referencia):\n\n{lesson_md[:6000]}")
    return "\n\n".join(parts)


def run_script(
    task_input: str,
    *,
    client,
    model: str,
    soul_md: str = "",
    agents_md: str = "",
) -> str:
    prompt = compose_system_prompt(
        SCRIPT_SPEC, soul_md or DEFAULT_SOUL, agents_md or DEFAULT_AGENTS_MD
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": task_input},
        ],
        temperature=0.6,
    )
    return (response.choices[0].message.content or "").strip() + "\n"
