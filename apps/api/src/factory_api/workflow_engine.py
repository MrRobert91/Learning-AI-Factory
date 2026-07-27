"""Compile declarative linear workflows into resumable LangGraph graphs.

Review policy is frozen from the selected profile into each step's overrides.
Human approval always lives in a node separate from expensive agent calls; a
feedback decision cycles back to the same agent and creates a new artifact
version before approval is requested again.
"""

import sqlite3
from contextlib import contextmanager
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from factory_api.config import get_settings
from factory_api.run_control import checkpoint, load_scope_state, save_scope_state

VALID_AGENTS = (
    "curator",
    "planner",
    "lessons",
    "slides",
    "script",
    "voice",
    "video",
    "publisher",
)
AGENT_INPUTS: dict[str, tuple[str, ...]] = {
    "curator": (),
    "planner": ("research_brief",),
    "lessons": ("research_brief", "course_plan"),
    "slides": ("course_plan", "lesson_content"),
    "script": ("slide_deck",),
    "voice": ("teaching_script",),
    "video": ("voice_script", "slide_deck"),
    "publisher": ("video",),
}
AGENT_OUTPUTS: dict[str, tuple[str, ...]] = {
    "curator": ("research_brief",),
    "planner": ("course_plan",),
    "lessons": ("lesson_content",),
    "slides": ("slide_deck",),
    "script": ("teaching_script",),
    "voice": ("voice_script",),
    "video": ("video", "subtitles"),
    "publisher": ("publication_package", "thumbnail"),
}
AGENT_LABELS = {
    "curator": "Curador de contenido",
    "planner": "Diseñador de curso",
    "lessons": "Generador de lecciones",
    "slides": "Diseñador de slides",
    "script": "Guion docente",
    "voice": "Adaptación a voz",
    "video": "Montaje de vídeo",
    "publisher": "Publicación",
}


def missing_agent_inputs(agent: str, available: set[str]) -> list[str]:
    return [type_ for type_ in AGENT_INPUTS.get(agent, ()) if type_ not in available]


def missing_workflow_inputs(definition: dict, available: set[str]) -> list[str]:
    """Return inputs that a workflow cannot produce before they are needed."""
    simulated = set(available)
    missing: list[str] = []
    for step in definition.get("steps", []):
        for type_ in missing_agent_inputs(step.get("agent", ""), simulated):
            if type_ not in missing:
                missing.append(type_)
        simulated.update(AGENT_OUTPUTS.get(step.get("agent", ""), ()))
    return missing


class WorkflowState(TypedDict, total=False):
    payload: dict[str, Any]
    results: dict[str, Any]
    review_summaries: dict[str, Any]
    human_reviews: dict[str, Any]
    human_actions: dict[str, Any]


def _review_policy(step: dict) -> tuple[bool, int, str | None]:
    overrides = step.get("overrides", {})
    return (
        bool(overrides.get("automatic_review_enabled", False)),
        int(overrides.get("max_automatic_regenerations", 0) or 0),
        overrides.get("evaluator_model"),
    )


def _human_review_enabled(step: dict) -> bool:
    return bool(step.get("overrides", {}).get("human_review_enabled", False))


def validate_definition(definition: dict) -> list[str]:
    """Return validation problems; an empty list means the definition is valid."""
    problems: list[str] = []
    steps = definition.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["El workflow debe tener al menos un paso"]
    available = {"course_idea_brief"}
    first_agent = steps[0].get("agent")
    if first_agent in VALID_AGENTS:
        available.update(AGENT_INPUTS[first_agent])
    seen: set[str] = set()
    for i, step in enumerate(steps):
        agent = step.get("agent")
        if agent not in VALID_AGENTS:
            problems.append(f"Paso {i + 1}: agente inválido '{agent}'")
            continue
        if agent in seen:
            problems.append(f"Paso {i + 1}: el agente '{agent}' ya está incluido")
        missing = set(AGENT_INPUTS[agent]) - available
        if missing:
            names = ", ".join(sorted(missing))
            problems.append(
                f"Paso {i + 1}: '{agent}' necesita artefactos que aún no existen: {names}"
            )
        seen.add(agent)
        available.update(AGENT_OUTPUTS[agent])
    return problems


@contextmanager
def open_checkpointer():
    settings = get_settings()
    path = settings.data_dir / "db" / "checkpoints.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        yield SqliteSaver(conn)
    finally:
        conn.close()


def _artifact_ids(result: dict | None) -> list[str]:
    if not result:
        return []
    if result.get("artifact_ids"):
        return list(result["artifact_ids"])
    return [result["artifact_id"]] if result.get("artifact_id") else []


def build_workflow_graph(
    definition: dict, job_id: str, handlers: dict, append_event, evaluator=None
):
    """Compile a workflow whose automatic and human review policies are frozen."""
    graph: StateGraph = StateGraph(WorkflowState)
    previous = START

    for index, step in enumerate(definition["steps"]):
        agent = step["agent"]
        step_number = index + 1
        review_key = f"{step_number}:{agent}"
        node_name = f"step{step_number}_{agent}"
        automatic_enabled, max_regenerations, evaluator_model = _review_policy(step)
        human_enabled = _human_review_enabled(step)

        def make_agent_node(
            step=step,
            agent=agent,
            step_number=step_number,
            review_key=review_key,
            automatic_enabled=automatic_enabled,
            human_enabled=human_enabled,
        ):
            def node(state: WorkflowState) -> WorkflowState:
                action = state.get("human_actions", {}).get(review_key, {})
                review_history = state.get("human_reviews", {}).get(review_key, {})
                human_cycle = len(review_history.get("cycles", []))
                feedback = (
                    action.get("feedback", "")
                    if action.get("decision") == "regenerate"
                    else ""
                )
                append_event(
                    job_id,
                    "stage",
                    f"Paso {step_number}: {AGENT_LABELS.get(agent, agent)} — "
                    + ("regenerando con feedback" if feedback else "iniciando"),
                    {"agent": agent, "step": step_number, "status": "running"},
                )
                stage_payload = {
                    **state["payload"],
                    **step.get("overrides", {}),
                    "_workflow_step": step_number,
                }
                control_scope = (
                    f"workflow:{step_number}:{agent}:human-cycle:{human_cycle}"
                )
                stage_payload["_control_scope"] = control_scope
                if feedback:
                    stage_payload["revision_feedback"] = feedback
                checkpoint(
                    job_id,
                    "workflow",
                    current_unit=None,
                    next_unit=f"{control_scope}:agent",
                    message=f"Preparando el paso {step_number}: {agent}",
                )
                result = handlers[f"{agent}_run"](job_id, stage_payload)
                checkpoint(
                    job_id,
                    "workflow",
                    current_unit=f"{control_scope}:agent",
                    next_unit=(
                        f"workflow:{step_number}:{agent}:automatic-review"
                        if automatic_enabled
                        else f"workflow:{step_number}:{agent}:human-approval"
                        if human_enabled
                        else None
                    ),
                    message=f"Paso {step_number}: {agent} completado",
                )
                results = {**state.get("results", {}), agent: result}
                if not automatic_enabled and not human_enabled:
                    append_event(
                        job_id,
                        "stage",
                        f"Paso {step_number}: {agent} completado",
                        {"agent": agent, "step": step_number, "status": "done"},
                    )
                return {"results": results}

            return node

        graph.add_node(node_name, make_agent_node())
        graph.add_edge(previous, node_name)
        step_exit = node_name

        if automatic_enabled and evaluator is not None:
            eval_name = f"eval{step_number}_{agent}"

            def make_eval_node(
                step=step,
                agent=agent,
                step_number=step_number,
                review_key=review_key,
                max_regenerations=max_regenerations,
                evaluator_model=evaluator_model,
                human_enabled=human_enabled,
            ):
                def node(state: WorkflowState) -> WorkflowState:
                    results = dict(state.get("results", {}))
                    summaries = dict(state.get("review_summaries", {}))
                    stage_payload = {
                        **state["payload"],
                        **step.get("overrides", {}),
                        "_workflow_step": step_number,
                    }
                    human_history = state.get("human_reviews", {}).get(review_key, {})
                    human_cycle = len(human_history.get("cycles", []))
                    control_scope = (
                        f"workflow:{step_number}:{agent}:human-cycle:{human_cycle}:"
                        "automatic-review"
                    )
                    review_state = load_scope_state(job_id, control_scope)
                    if isinstance(review_state.get("result"), dict):
                        results[agent] = review_state["result"]
                    evaluations = int(review_state.get("evaluations", 0))
                    regenerations = int(review_state.get("regenerations", 0))
                    if isinstance(review_state.get("summary"), dict):
                        summaries[review_key] = review_state["summary"]
                        return {"results": results, "review_summaries": summaries}
                    while True:
                        verdict = review_state.get("pending_verdict")
                        feedback = str(review_state.get("pending_feedback", ""))
                        if verdict is None:
                            checkpoint(
                                job_id,
                                "workflow_evaluation",
                                current_unit=None,
                                next_unit=f"{control_scope}:evaluation:{evaluations + 1}",
                                message=f"Preparando evaluación de {agent}",
                            )
                            append_event(
                                job_id,
                                "evaluation",
                                f"Evaluación automática de {agent} iniciada",
                                {
                                    "agent": agent,
                                    "step": step_number,
                                    "status": "running",
                                    "model": evaluator_model,
                                    "evaluation": evaluations + 1,
                                },
                            )
                            try:
                                verdict, feedback = evaluator(
                                    agent, results.get(agent), step_number
                                )
                            except Exception as exc:
                                evaluations += 1
                                summary = {
                                    "agent": agent,
                                    "evaluations": evaluations,
                                    "regenerations": regenerations,
                                    "final_result": "evaluator_error",
                                    "model": evaluator_model,
                                }
                                save_scope_state(
                                    job_id,
                                    control_scope,
                                    {
                                        "evaluations": evaluations,
                                        "regenerations": regenerations,
                                        "result": results.get(agent),
                                        "summary": summary,
                                    },
                                )
                                append_event(
                                    job_id,
                                    "evaluation",
                                    f"La evaluación de {agent} falló; se conserva la salida",
                                    {
                                        "agent": agent,
                                        "step": step_number,
                                        "status": "warning",
                                        "technical_error": True,
                                        "error": str(exc),
                                        "model": evaluator_model,
                                    },
                                )
                                summaries[review_key] = summary
                                if not human_enabled:
                                    append_event(
                                        job_id,
                                        "stage",
                                        f"Paso {step_number}: {agent} completado con advertencia",
                                        {
                                            "agent": agent,
                                            "step": step_number,
                                            "status": "done",
                                        },
                                    )
                                checkpoint(
                                    job_id,
                                    "workflow_evaluation",
                                    current_unit=f"{control_scope}:evaluation:{evaluations}",
                                    next_unit=None,
                                    message=f"Evaluación de {agent} finalizada con advertencia",
                                )
                                return {
                                    "results": results,
                                    "review_summaries": summaries,
                                }
                            evaluations += 1
                            review_state = {
                                "evaluations": evaluations,
                                "regenerations": regenerations,
                                "pending_verdict": verdict,
                                "pending_feedback": feedback,
                                "result": results.get(agent),
                            }
                            save_scope_state(job_id, control_scope, review_state)
                            checkpoint(
                                job_id,
                                "workflow_evaluation",
                                current_unit=f"{control_scope}:evaluation:{evaluations}",
                                next_unit=(
                                    f"{control_scope}:regeneration:{regenerations + 1}"
                                    if verdict != "pass"
                                    and regenerations < max_regenerations
                                    else None
                                ),
                                message=f"Evaluación {evaluations} de {agent} completada",
                            )
                        if verdict == "pass":
                            summary = {
                                "agent": agent,
                                "evaluations": evaluations,
                                "regenerations": regenerations,
                                "final_result": "pass",
                                "model": evaluator_model,
                            }
                            summaries[review_key] = summary
                            save_scope_state(
                                job_id,
                                control_scope,
                                {**review_state, "summary": summary},
                            )
                            if not human_enabled:
                                append_event(
                                    job_id,
                                    "stage",
                                    f"Paso {step_number}: {agent} completado",
                                    {"agent": agent, "step": step_number, "status": "done"},
                                )
                            return {"results": results, "review_summaries": summaries}
                        if regenerations >= max_regenerations:
                            destination = "human_approval" if human_enabled else "continue"
                            summary = {
                                "agent": agent,
                                "evaluations": evaluations,
                                "regenerations": regenerations,
                                "final_result": "exhausted",
                                "destination": destination,
                                "feedback": feedback,
                                "model": evaluator_model,
                            }
                            summaries[review_key] = summary
                            save_scope_state(
                                job_id,
                                control_scope,
                                {**review_state, "summary": summary},
                            )
                            if not human_enabled:
                                append_event(
                                    job_id,
                                    "evaluation",
                                    f"{agent} agotó {max_regenerations} regeneraciones; "
                                    "el workflow continúa con advertencia",
                                    {
                                        "agent": agent,
                                        "step": step_number,
                                        "status": "warning",
                                        "verdict": verdict,
                                        "feedback": feedback,
                                        "destination": "continue",
                                    },
                                )
                                append_event(
                                    job_id,
                                    "stage",
                                    f"Paso {step_number}: {agent} completado con advertencia",
                                    {"agent": agent, "step": step_number, "status": "done"},
                                )
                            return {"results": results, "review_summaries": summaries}
                        next_regeneration = regenerations + 1
                        checkpoint(
                            job_id,
                            "workflow_evaluation",
                            current_unit=f"{control_scope}:evaluation:{evaluations}",
                            next_unit=f"{control_scope}:regeneration:{next_regeneration}",
                            message=f"Preparando regeneración de {agent}",
                        )
                        append_event(
                            job_id,
                            "evaluation",
                            f"Regeneración {next_regeneration}/{max_regenerations} de {agent} "
                            "con feedback del evaluador…",
                            {
                                "agent": agent,
                                "step": step_number,
                                "status": "regenerating",
                                "regeneration": next_regeneration,
                                "max_regenerations": max_regenerations,
                                "feedback": feedback,
                            },
                        )
                        results[agent] = handlers[f"{agent}_run"](
                            job_id,
                            {
                                **stage_payload,
                                "revision_feedback": feedback,
                                "_control_scope": (
                                    f"{control_scope}:regeneration:{next_regeneration}"
                                ),
                            },
                        )
                        regenerations = next_regeneration
                        review_state = {
                            "evaluations": evaluations,
                            "regenerations": regenerations,
                            "result": results.get(agent),
                        }
                        save_scope_state(job_id, control_scope, review_state)
                        checkpoint(
                            job_id,
                            "workflow_evaluation",
                            current_unit=f"{control_scope}:regeneration:{regenerations}",
                            next_unit=f"{control_scope}:evaluation:{evaluations + 1}",
                            message=f"Regeneración {regenerations} de {agent} completada",
                        )

                return node

            graph.add_node(eval_name, make_eval_node())
            graph.add_edge(step_exit, eval_name)
            step_exit = eval_name

        if human_enabled:
            ready_name = f"ready{step_number}_{agent}"
            approval_name = f"approval{step_number}_{agent}"
            done_name = f"approved{step_number}_{agent}"

            def make_ready_node(agent=agent, step_number=step_number):
                def node(state: WorkflowState) -> WorkflowState:
                    checkpoint(
                        job_id,
                        "workflow_approval",
                        current_unit=f"workflow:{step_number}:{agent}:agent",
                        next_unit=f"workflow:{step_number}:{agent}:human-approval",
                        message=f"Preparando revisión humana de {agent}",
                    )
                    append_event(
                        job_id,
                        "stage",
                        f"Paso {step_number}: {agent} espera revisión humana",
                        {"agent": agent, "step": step_number, "status": "waiting_approval"},
                    )
                    return {}

                return node

            def make_approval_node(
                agent=agent, step_number=step_number, review_key=review_key
            ):
                def node(state: WorkflowState) -> WorkflowState:
                    history = dict(state.get("human_reviews", {}))
                    current = dict(history.get(review_key, {}))
                    cycles = list(current.get("cycles", []))
                    decision = interrupt(
                        {
                            "step": step_number,
                            "agent": agent,
                            "result": state.get("results", {}).get(agent),
                            "automatic_review": state.get("review_summaries", {}).get(
                                review_key
                            ),
                            "human_cycles": len(cycles),
                        }
                    )
                    approved = bool((decision or {}).get("approved", False))
                    feedback = str((decision or {}).get("feedback", "")).strip()
                    if not approved and not feedback:
                        raise ValueError("Escribe feedback para regenerar la fase")
                    result = state.get("results", {}).get(agent)
                    cycles.append(
                        {
                            "cycle": len(cycles) + 1,
                            "decision": "approved" if approved else "regenerate",
                            "feedback": feedback,
                            "artifact_ids": _artifact_ids(result),
                            "automatic_review": state.get(
                                "review_summaries", {}
                            ).get(review_key),
                        }
                    )
                    history[review_key] = {
                        "agent": agent,
                        "step": step_number,
                        "cycles": cycles,
                        "final_decision": "approved" if approved else None,
                    }
                    actions = dict(state.get("human_actions", {}))
                    actions[review_key] = {
                        "decision": "approved" if approved else "regenerate",
                        "feedback": feedback,
                    }
                    append_event(
                        job_id,
                        "approval",
                        (
                            f"Paso {step_number}: {agent} aprobado"
                            if approved
                            else f"Paso {step_number}: {agent} se regenerará con feedback"
                        ),
                        {
                            "agent": agent,
                            "step": step_number,
                            "status": "done" if approved else "regenerating",
                            "human_cycle": len(cycles),
                            "feedback": feedback,
                        },
                    )
                    return {"human_reviews": history, "human_actions": actions}

                return node

            def route_after_approval(state: WorkflowState, review_key=review_key) -> str:
                action = state.get("human_actions", {}).get(review_key, {})
                return "regenerate" if action.get("decision") == "regenerate" else "approved"

            graph.add_node(ready_name, make_ready_node())
            graph.add_edge(step_exit, ready_name)
            graph.add_node(approval_name, make_approval_node())
            graph.add_edge(ready_name, approval_name)
            graph.add_node(done_name, lambda _state: {})
            graph.add_conditional_edges(
                approval_name,
                route_after_approval,
                {"regenerate": node_name, "approved": done_name},
            )
            step_exit = done_name

        previous = step_exit

    graph.add_edge(previous, END)
    return graph
