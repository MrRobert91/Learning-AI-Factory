"""Slide Designer: turns a lesson into a Marp slide deck (one-shot)."""

import re

from factory_agents.runtime import AgentSpec, compose_system_prompt, register

SLIDES_BASE_PROMPT = """\
Eres el Diseñador de Slides de AI Learning Factory. Conviertes el contenido de una \
lección en una presentación Marp (Markdown) clara y profesional, pensada para \
acompañar la voz de un profesor (en directo o narrada en vídeo).

Reglas de diseño:
- Las slides NO son el guion: contienen lo esencial (ideas fuerza, diagramas, código), \
el profesor amplía el resto.
- Una idea por slide. Máximo ~5 bullets o ~12 líneas de código por slide.
- Usa `---` para separar slides. La primera slide es la portada de la lección.
- El código va en bloques con lenguaje (```python). Divide los ejemplos largos.
- Cierra con una slide de resumen que mapee al objetivo de la lección.

Formato de salida: ÚNICAMENTE el Markdown de Marp, empezando exactamente con el \
front-matter:

---
marp: true
theme: {theme}
size: {slide_size}
paginate: true
---

No añadas explicaciones fuera del Markdown.
"""

DEFAULT_SOUL = """\
Diseñador sobrio: la claridad es el estilo. Odia las slides-muro-de-texto tanto como \
las slides vacías de una palabra. Piensa en cómo se verá cada slide congelada en el \
formato objetivo, tanto en YouTube como en una pantalla móvil.
"""

DEFAULT_AGENTS_MD = """\
- Entre 8 y 18 slides por lección.
- Títulos de slide de máximo 8 palabras.
- Si la lección tiene código verificado, inclúyelo tal cual (no lo reescribas).
- Idioma: el del curso.
"""

SLIDES_SPEC = register(
    AgentSpec(
        name="slides",
        display_name="Diseñador de slides",
        description=(
            "Convierte cada lección en una presentación Marp clara y "
            "profesional, lista para renderizar a HTML/PDF/PPTX."
        ),
        base_prompt=SLIDES_BASE_PROMPT,
        consumes=("lesson_content",),
        produces=("slide_deck",),
        default_soul_md=DEFAULT_SOUL,
        default_agents_md=DEFAULT_AGENTS_MD,
    )
)

MARP_THEME = "default"


def render_slides_input(
    lesson_md: str, course_title: str, style: str, orientation: str = "horizontal"
) -> str:
    layout = (
        "vertical 9:16 (1080x1920), optimizado para móvil; usa bloques cortos "
        "y distribuye el contenido en más slides"
        if orientation == "vertical"
        else "horizontal 16:9 (1920x1080)"
    )
    return (
        f"Curso: {course_title}\n"
        f"Estilo visual/tono: {style or 'profesional y sobrio'}\n\n"
        f"Formato de las slides: {layout}.\n\n"
        f"Convierte esta lección en slides Marp:\n\n{lesson_md}"
    )


def clean_marp_output(text: str) -> str:
    """Strip surrounding code fences the model may add around the deck."""
    text = text.strip()
    fenced = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    return text + "\n"


def apply_slide_orientation(deck: str, orientation: str) -> str:
    """Enforce a stable Marp canvas regardless of the model response."""
    size = "1080px 1920px" if orientation == "vertical" else "16:9"
    lines = deck.replace("\r\n", "\n").splitlines()
    if not lines or lines[0].strip() != "---":
        lines = ["---", "marp: true", f"size: {size}", "paginate: true", "---", "", *lines]
        return "\n".join(lines).rstrip() + "\n"
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return deck
    frontmatter = [line for line in lines[1:end] if not line.strip().startswith("size:")]
    frontmatter.append(f"size: {size}")
    return "\n".join(["---", *frontmatter, "---", *lines[end + 1 :]]).rstrip() + "\n"


def run_slides(
    task_input: str,
    *,
    client,
    model: str,
    soul_md: str = "",
    agents_md: str = "",
    orientation: str = "horizontal",
) -> str:
    slide_size = "1080px 1920px" if orientation == "vertical" else "16:9"
    prompt = compose_system_prompt(
        SLIDES_SPEC, soul_md or DEFAULT_SOUL, agents_md or DEFAULT_AGENTS_MD
    ).replace("{theme}", MARP_THEME).replace("{slide_size}", slide_size)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": task_input},
        ],
        temperature=0.5,
    )
    deck = clean_marp_output(response.choices[0].message.content or "")
    if "marp: true" not in deck:
        deck = f"---\nmarp: true\ntheme: {MARP_THEME}\npaginate: true\n---\n\n" + deck
    return apply_slide_orientation(deck, orientation)
