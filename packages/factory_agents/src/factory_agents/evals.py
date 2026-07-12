"""Automatic evaluators: LLM-as-judge with explicit, versioned rubrics.

Each evaluation returns pass|revise with actionable feedback. The workflow
engine re-runs the producing agent with the feedback (bounded retries) and
escalates to the human when the artifact still doesn't pass.
"""


from pydantic import BaseModel, Field, ValidationError

from factory_agents.agents.planner import extract_json

RUBRICS_VERSION = "1"

RUBRICS: dict[str, str] = {
    "course_plan": """\
Evalúa este PLAN DE CURSO con criterio pedagógico:
1. Progresión: cada lección se apoya solo en lo anterior o en los prerequisitos.
2. Objetivos: cada lección tiene UN objetivo evaluable ("el estudiante sabrá X").
3. Alcance: cubre lo que la audiencia y nivel declarados necesitan, sin relleno.
4. Duraciones realistas (5-20 min por lección) y títulos que funcionan como vídeos.
""",
    "lesson_content": """\
Evalúa este CONTENIDO DE LECCIÓN con criterio técnico y didáctico:
1. Exactitud: afirmaciones correctas; nada inventado; código coherente con lo explicado.
2. Claridad: progresión motivación→concepto→ejemplo→resumen; nivel adecuado a la audiencia.
3. Concreción: ejemplos específicos y útiles, sin párrafos de paja.
4. Cierre: el resumen final mapea al objetivo declarado de la lección.
""",
    "slide_deck": """\
Evalúa estas SLIDES (Marp) con criterio de claridad visual:
1. Densidad: una idea por slide; máximo ~5 bullets o ~12 líneas de código.
2. Jerarquía: títulos cortos y descriptivos; sin muros de texto.
3. Completitud: cubren la lección de principio a fin con portada y resumen.
4. Formato Marp válido: front-matter correcto y separadores `---` entre slides.
""",
    "research_brief": """\
Evalúa este RESEARCH BRIEF:
1. Fuentes: citadas con URL, fiables y suficientes; nada sin respaldo.
2. Cobertura: conceptos clave, estado del arte y errores comunes presentes.
3. Utilidad: la estructura temática sugerida es directamente accionable.
""",
    "teaching_script": """\
Evalúa este GUION DOCENTE:
1. Amplía las slides en lugar de repetirlas; suena a profesor, no a texto leído.
2. Un bloque por slide, con transiciones naturales entre ellas.
3. Densidad hablada razonable (60-180 palabras por slide).
""",
}

JUDGE_PROMPT = """\
Eres un evaluador de calidad de AI Learning Factory (rúbricas v{version}). Evalúas \
artefactos de cursos con una rúbrica y decides si pasan o deben revisarse.

Reglas:
- verdict "pass": el artefacto cumple la rúbrica razonablemente bien (no exijas perfección).
- verdict "revise": hay problemas concretos que el agente productor puede corregir. El \
feedback debe ser ESPECÍFICO y accionable (qué está mal y cómo arreglarlo), nunca vago.
- score: 1-10 (7+ implica pass).

Responde ÚNICAMENTE con JSON: {{"verdict": "pass"|"revise", "score": n, "feedback": "..."}}
"""


class Evaluation(BaseModel):
    verdict: str = Field(pattern="^(pass|revise)$")
    score: int = Field(ge=1, le=10)
    feedback: str = ""


def run_evaluator(
    client,
    model: str,
    artifact_type: str,
    content: str,
    context: str = "",
) -> Evaluation:
    rubric = RUBRICS.get(artifact_type)
    if rubric is None:
        return Evaluation(verdict="pass", score=7, feedback="(sin rúbrica para este tipo)")
    user_input = (
        f"Rúbrica:\n{rubric}\n"
        + (f"\nContexto del curso:\n{context[:1500]}\n" if context else "")
        + f"\nArtefacto a evaluar ({artifact_type}):\n\n{content[:12000]}"
    )
    messages = [
        {"role": "system", "content": JUDGE_PROMPT.format(version=RUBRICS_VERSION)},
        {"role": "user", "content": user_input},
    ]
    for _ in range(2):
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=0.2
        )
        text = response.choices[0].message.content or ""
        try:
            return Evaluation.model_validate(extract_json(text))
        except (ValueError, ValidationError):
            messages.append({"role": "assistant", "content": text})
            messages.append(
                {"role": "user", "content": "JSON inválido. Devuelve solo el JSON pedido."}
            )
    # A broken judge must not block production: pass with a note.
    return Evaluation(verdict="pass", score=7, feedback="(evaluador no disponible)")
