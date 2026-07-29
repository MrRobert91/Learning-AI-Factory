"""Slide Designer: turns a lesson into a Marp slide deck (one-shot)."""

import re

from factory_agents.runtime import AgentSpec, compose_system_prompt, register
from factory_agents.tools.marp import apply_marp_orientation

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
{size_directive}
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
- Ajusta el número de slides al presupuesto programático y a la orientación recibidos.
- Títulos de slide de máximo 8 palabras.
- Si la lección tiene código verificado, inclúyelo tal cual (no lo reescribas).
- Idioma: el del curso.
"""

IMAGE_MARKER_PROMPT = """\

Generación de imágenes activada:
- Selecciona como máximo 6 slides que se beneficien realmente de una ilustración.
- Nunca añadas más de una imagen por slide.
- Evita portada, slides centradas en código y resumen, salvo que la imagen aporte valor claro.
- Para cada imagen inserta un comentario JSON válido en la posición de la slide.
  Ejemplo: <!-- factory-image {"prompt":"visual prompt","layout":"right","alt":"concept"} -->
- `layout` solo puede ser `left` o `right`; nunca uses una imagen generada como fondo.
- Reduce la densidad del texto para dejar una columna amplia y legible junto al panel visual.
- El prompt debe ilustrar el concepto concreto de esa slide, describir sujeto, acción,
  composición y metáfora visual, estar escrito en inglés y no incluir instrucciones de estilo.
- La imagen no debe contener texto, letras, etiquetas, captions ni elementos de interfaz.
- No escribas rutas, Markdown de imagen ni URLs: el sistema sustituirá el comentario por el asset.
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
        "vertical 9:16 real (1080x1920), optimizado para TikTok, YouTube Shorts "
        "y lectura en un móvil; usa una sola columna, tipografía grande, bloques "
        "cortos y distribuye el contenido a lo largo del lienzo"
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
    return apply_marp_orientation(deck, orientation)


def run_slides(
    task_input: str,
    *,
    client,
    model: str,
    soul_md: str = "",
    agents_md: str = "",
    orientation: str = "horizontal",
    images_enabled: bool = False,
) -> str:
    size_directive = "" if orientation == "vertical" else "size: 16:9"
    prompt = compose_system_prompt(
        SLIDES_SPEC, soul_md or DEFAULT_SOUL, agents_md or DEFAULT_AGENTS_MD
    ).replace("{theme}", MARP_THEME).replace("{size_directive}", size_directive)
    if orientation == "vertical":
        prompt += """

Reglas adicionales para composición vertical móvil:
- Diseña en una sola columna y aprovecha el recorrido vertical del lienzo 9:16.
- Usa como máximo 4 bullets breves por slide y evita tablas anchas o columnas paralelas.
- Mantén títulos en una o dos líneas y prioriza elementos grandes legibles en móvil.
- Reparte conceptos densos en más slides; no reduzcas el texto para hacerlo caber.
"""
    if images_enabled:
        prompt += IMAGE_MARKER_PROMPT
    else:
        prompt += "\nNo incluyas marcadores `factory-image` ni referencias a imágenes generadas.\n"
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
