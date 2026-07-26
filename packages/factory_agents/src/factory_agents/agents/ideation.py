"""Ideation Assistant: refines a vague course idea into a CourseIdeaBrief.

Purely conversational agent. It bounces the user's idea back with proposals
and structured multiple-choice questions (3-4 options rendered as clickable
cards by the UI), optionally checks demand via web search, and finishes by
proposing a structured brief.

The turn protocol is transport-agnostic: the caller passes the conversation
history and gets back a list of AgentEvents to persist/render. A turn ends
when the agent asks a question, proposes a brief, or answers with plain text.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from factory_agents.contracts import CourseIdeaBrief
from factory_agents.runtime import AgentSpec, compose_system_prompt, register
from factory_agents.tools.sources import (
    list_source_documents,
    read_source_document,
    search_source_documents,
)
from factory_agents.tools.web_search import format_results, web_search

EventKind = Literal["text", "question", "search", "source", "brief"]


@dataclass
class AgentEvent:
    kind: EventKind
    content: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class HistoryItem:
    """One persisted conversation item, as stored by the API layer."""

    role: Literal["user", "assistant"]
    kind: str  # text | question | answer | search | brief
    content: str
    payload: dict[str, Any] = field(default_factory=dict)


SYSTEM_PROMPT = """\
Eres el Asistente de Ideación de AI Learning Factory, una plataforma que fabrica \
cursos online con agentes de IA. Tu trabajo es ayudar al usuario a transformar una \
idea vaga de curso o material educativo en una especificación clara (brief) que \
luego usará el agente de investigación.

Cómo trabajas:
- Rebotas la idea con el usuario: propones ángulos, detectas ambigüedades y ayudas \
a decidir. Eres un interlocutor con criterio, no un formulario.
- Para afinar decisiones usa la herramienta `ask_user_question` con 3 a 6 opciones \
concretas y bien diferenciadas (la interfaz las muestra como tarjetas clicables y \
el usuario siempre puede responder texto libre). Haz UNA pregunta por turno, la más \
valiosa en ese momento. No preguntes lo que ya se ha dicho.
- Mientras se construye el brief, cada turno debe terminar usando
`ask_user_question` con varias opciones clicables. La \u00fanica excepci\u00f3n es el turno
en el que llamas a `propose_brief`: ah\u00ed no hagas una pregunta adicional.
- Cubre progresivamente: audiencia y conocimientos previos, nivel, objetivos de \
aprendizaje, alcance, ángulo diferencial, idioma, estilo, formato de salida \
(vídeo completo, solo diapositivas, o guion docente) y duración/estructura.
- Antes de proponer el brief es obligatorio que el usuario elija la duración. Ofrece \
estas seis tarjetas: Microvídeo (1×1×1 min), Minicurso (1×3×5 min), Curso breve \
(2×3×8 min), Curso estándar (3×4×10 min), Curso completo (5×4×15 min) y \
Personalizado. Si elige Personalizado, pregunta módulos 1–5, lecciones por módulo \
1–5 y minutos por vídeo 1–60. Confirma el total de vídeos y minutos.
- Si dudas de la demanda o del enfoque de un tema puedes usar `web_search` para \
ver qué existe ya, y comentar brevemente lo que encuentres.
- Respeta la política de investigación indicada al final del prompt. Las fuentes \
aportadas se citan con su ID estable y ubicación; nunca inventes contenido ausente.
- Cuando tengas suficiente información (típicamente tras 3-6 preguntas), llama a \
`propose_brief` con el brief completo. No alargues la conversación \
innecesariamente. Tras proponer el brief, el usuario puede pedir cambios: si lo \
hace, vuelve a llamar a `propose_brief` con la versión corregida.
- Responde siempre en el idioma del usuario. Sé conciso y directo.
"""

DEFAULT_SOUL = """\
Curioso y con criterio propio: propone, no solo pregunta. Entusiasta sin ser \
vendedor. Detecta cuando el usuario ya lo tiene claro y no le hace perder el \
tiempo con preguntas innecesarias.
"""

DEFAULT_AGENTS_MD = """\
- Haz como máximo 6 preguntas por sesión; si con menos basta, mejor.
- Cada pregunta debe cambiar de verdad el brief resultante; nada de relleno.
- El brief final debe ser accionable por un investigador sin contexto adicional.
"""

IDEATION_SPEC = register(
    AgentSpec(
        name="ideation",
        display_name="Asistente de Ideación",
        description=(
            "Convierte una idea vaga en un brief de curso mediante conversación "
            "y preguntas con 3-6 opciones."
        ),
        base_prompt=SYSTEM_PROMPT,
        tool_names=(
            "ask_user_question",
            "list_sources",
            "search_sources",
            "read_source",
            "web_search",
            "propose_brief",
        ),
        produces=("course_idea_brief",),
        default_soul_md=DEFAULT_SOUL,
        default_agents_md=DEFAULT_AGENTS_MD,
        kind="conversational",
    )
)

_ASK_USER_QUESTION_TOOL = {
    "type": "function",
    "function": {
        "name": "ask_user_question",
        "description": (
            "Plantea al usuario una pregunta con 3-6 opciones de respuesta para "
            "afinar la idea del curso. La UI las muestra como tarjetas clicables."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "La pregunta, clara y concreta"},
                "options": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "Opción corta (1-6 palabras)",
                            },
                            "description": {
                                "type": "string",
                                "description": "Qué implica elegir esta opción",
                            },
                        },
                        "required": ["label"],
                    },
                },
            },
            "required": ["question", "options"],
        },
    },
}

_WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Búsqueda web ligera para validar demanda, competencia o enfoque de un tema."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}

_PROPOSE_BRIEF_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_brief",
        "description": (
            "Propone el brief final del curso una vez la idea está suficientemente "
            "afinada. El usuario podrá revisarlo y pedir cambios."
        ),
        "parameters": CourseIdeaBrief.model_json_schema(),
    },
}

_LIST_SOURCES_TOOL = {
    "type": "function",
    "function": {
        "name": "list_sources",
        "description": "Lista las fuentes aportadas y sus IDs estables.",
        "parameters": {"type": "object", "properties": {}},
    },
}

_SEARCH_SOURCES_TOOL = {
    "type": "function",
    "function": {
        "name": "search_sources",
        "description": "Busca extractos relevantes dentro de las fuentes aportadas.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}

_READ_SOURCE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_source",
        "description": "Lee una fuente o una ubicación concreta sin volcar todo el corpus.",
        "parameters": {
            "type": "object",
            "properties": {
                "source_id": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["source_id"],
        },
    },
}

TOOLS = [_ASK_USER_QUESTION_TOOL, _WEB_SEARCH_TOOL, _PROPOSE_BRIEF_TOOL]

MAX_TOOL_ROUNDS = 4


def _render_history(history: list[HistoryItem]) -> list[dict[str, Any]]:
    """Render persisted history as plain chat messages.

    Past structured events are flattened to text so the transcript stays
    model-agnostic; native tool-calling is only used within the live turn.
    """
    messages: list[dict[str, Any]] = []
    for item in history:
        if item.kind == "question":
            options = item.payload.get("options", [])
            lines = [item.content] + [
                f"- {o.get('label', '')}: {o.get('description', '')}".rstrip(": ")
                for o in options
            ]
            messages.append({"role": "assistant", "content": "\n".join(lines)})
        elif item.kind == "search":
            messages.append(
                {
                    "role": "assistant",
                    "content": f"[búsqueda web: {item.payload.get('query', '')}]\n{item.content}",
                }
            )
        elif item.kind == "brief":
            messages.append(
                {
                    "role": "assistant",
                    "content": "[brief propuesto]\n"
                    + json.dumps(item.payload, ensure_ascii=False, indent=2),
                }
            )
        else:
            messages.append({"role": item.role, "content": item.content})
    return messages


def run_ideation_turn(
    client,
    model: str,
    history: list[HistoryItem],
    soul_md: str = "",
    agents_md: str = "",
    on_progress: Callable[[str, str, dict[str, Any]], None] | None = None,
    research_mode: Literal[
        "provided_only", "provided_plus_web", "web_only"
    ] = "web_only",
    source_documents: list[dict[str, Any]] | None = None,
    max_source_queries: int | None = None,
) -> list[AgentEvent]:
    """Run one agent turn. Returns the events produced (to persist and render)."""
    system = compose_system_prompt(
        IDEATION_SPEC,
        soul_md or DEFAULT_SOUL,
        agents_md or DEFAULT_AGENTS_MD,
    )
    documents = source_documents or []
    ready_ids = [str(document.get("id")) for document in documents]
    policy_lines = [
        "# Política de investigación congelada",
        f"- Modo: {research_mode}",
        f"- IDs de fuentes disponibles: {', '.join(ready_ids) if ready_ids else 'ninguna'}",
    ]
    if research_mode == "provided_only":
        policy_lines.extend(
            [
                "- No tienes herramientas web y no debes usar conocimiento factual externo.",
                "- Toda afirmación factual debe citar `[source:<id> <ubicación>]`.",
                "- Declara literalmente `no cubierto por las fuentes` cuando falte información.",
            ]
        )
    elif research_mode == "provided_plus_web":
        policy_lines.append(
            "- Distingue claramente las fuentes aportadas de cualquier fuente web externa."
        )
    else:
        policy_lines.append("- La investigación web libre conserva el flujo habitual.")
    system += "\n\n" + "\n".join(policy_lines)
    available_tools = [_ASK_USER_QUESTION_TOOL, _PROPOSE_BRIEF_TOOL]
    if research_mode != "provided_only":
        available_tools.insert(1, _WEB_SEARCH_TOOL)
    if research_mode != "web_only" and documents:
        available_tools[1:1] = [
            _LIST_SOURCES_TOOL,
            _SEARCH_SOURCES_TOOL,
            _READ_SOURCE_TOOL,
        ]
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages += _render_history(history)

    events: list[AgentEvent] = []
    source_queries_used = 0
    if on_progress:
        on_progress(
            "stage",
            "Analizando la conversación y comprobando qué información falta.",
            {},
        )
    for round_index in range(MAX_TOOL_ROUNDS):
        if on_progress and round_index > 0:
            on_progress(
                "stage",
                "Integrando el resultado de la herramienta y preparando el siguiente paso.",
                {"round": round_index + 1},
            )
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=available_tools,
            temperature=0.7,
            tool_choice="required",
        )
        msg = response.choices[0].message

        if msg.content:
            events.append(AgentEvent(kind="text", content=msg.content))

        if not msg.tool_calls:
            break

        # Keep the native tool protocol within the live turn.
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
        )

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if on_progress:
                labels = {
                    "ask_user_question": "Preparando la pregunta más útil para completar el brief.",
                    "web_search": f"Consultando fuentes sobre: {args.get('query', '')}",
                    "list_sources": "Revisando el corpus aportado por el usuario.",
                    "search_sources": (
                        f"Buscando en las fuentes: {args.get('query', '')}"
                    ),
                    "read_source": (
                        f"Leyendo la fuente {args.get('source_id', '')} "
                        f"{args.get('location', '')}".strip()
                    ),
                    "propose_brief": "Construyendo y validando el brief estructurado.",
                }
                on_progress(
                    "tool_call",
                    labels.get(name, f"Llamando a la herramienta {name}."),
                    {"tool": name, "arguments": args},
                )

            if name == "ask_user_question":
                options = [o for o in args.get("options", []) if o.get("label")][:4]
                events.append(
                    AgentEvent(
                        kind="question",
                        content=args.get("question", ""),
                        payload={"options": options},
                    )
                )
                if on_progress:
                    on_progress(
                        "review",
                        "Pregunta revisada: cubre una decisión pendiente "
                        "y ofrece opciones concretas.",
                        {"tool": name},
                    )
                return events

            if name == "propose_brief":
                try:
                    brief = CourseIdeaBrief.model_validate(args)
                except ValidationError as exc:
                    if on_progress:
                        on_progress(
                            "review",
                            "La primera propuesta no pasó la validación; "
                            "corrigiendo su estructura.",
                            {"tool": name},
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"Brief inválido, corrige y reintenta: {exc}",
                        }
                    )
                    continue
                events.append(
                    AgentEvent(
                        kind="brief",
                        content="Brief propuesto",
                        payload=brief.model_dump(),
                    )
                )
                if on_progress:
                    on_progress(
                        "review",
                        "Brief revisado y validado contra el contrato de datos del curso.",
                        {"tool": name},
                    )
                return events

            if name == "web_search":
                query = args.get("query", "")
                formatted = format_results(web_search(query))
                events.append(
                    AgentEvent(kind="search", content=formatted, payload={"query": query})
                )
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": formatted}
                )
                if on_progress:
                    on_progress(
                        "tool_result",
                        "Búsqueda completada; contrastando los resultados con la idea del curso.",
                        {"tool": name, "query": query},
                    )
                continue

            if name in {"list_sources", "search_sources", "read_source"}:
                source_queries_used += 1
                if (
                    max_source_queries is not None
                    and source_queries_used > max_source_queries
                ):
                    result = (
                        f"(límite de {max_source_queries} consultas al corpus alcanzado; "
                        "continúa con los extractos ya consultados)"
                    )
                elif name == "list_sources":
                    result = list_source_documents(documents)
                elif name == "search_sources":
                    result = search_source_documents(
                        documents, str(args.get("query") or "")
                    )
                else:
                    result = read_source_document(
                        documents,
                        str(args.get("source_id") or ""),
                        str(args.get("location") or "") or None,
                    )
                events.append(
                    AgentEvent(
                        kind="source",
                        content=result,
                        payload={
                            "tool": name,
                            "query": args.get("query"),
                            "source_id": args.get("source_id"),
                            "location": args.get("location"),
                        },
                    )
                )
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result}
                )
                if on_progress:
                    on_progress(
                        "tool_result",
                        "Consulta al corpus completada con referencias trazables.",
                        {
                            "tool": name,
                            "source_id": args.get("source_id"),
                            "query": args.get("query"),
                        },
                    )
                continue

            if name not in {
                "ask_user_question",
                "propose_brief",
                "web_search",
                "list_sources",
                "search_sources",
                "read_source",
            }:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": f"Herramienta desconocida: {name}",
                    }
                )

    # Tool-round budget exhausted: make sure the user gets something.
    if not any(event.kind in ("question", "brief") for event in events):
        events.append(
            AgentEvent(
                kind="question",
                content="No he podido completar el paso. ¿Puedes reformular o darme más detalle?",
                payload={
                    "options": [
                        {
                            "label": "Afinar la audiencia",
                            "description": "Concretar para qui\u00e9n es el curso",
                        },
                        {
                            "label": "Definir los objetivos",
                            "description": "Decidir qu\u00e9 aprender\u00e1 el alumnado",
                        },
                        {
                            "label": "Explorar el formato",
                            "description": "Elegir v\u00eddeo, slides o guion",
                        },
                    ]
                },
            )
        )
    return events
