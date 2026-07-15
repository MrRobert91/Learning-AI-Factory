"""Workflow engine: compiles declarative linear chains into LangGraph graphs.

A workflow definition is JSON: {"steps": [{"agent": "curator",
"approval_after": true, "overrides": {...}}, ...]}. Each step becomes a
graph node that runs the matching job handler; steps marked with
approval_after are followed by an approval node that pauses the graph via
LangGraph's interrupt(), persisted in a SQLite checkpointer so the run can
resume later (even after a restart) when the human approves or rejects.
"""

import sqlite3
from contextlib import contextmanager
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from factory_api.config import get_settings

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


def missing_agent_inputs(agent: str, available: set[str]) -> list[str]:
    return [type_ for type_ in AGENT_INPUTS.get(agent, ()) if type_ not in available]


def missing_workflow_inputs(definition: dict, available: set[str]) -> list[str]:
    """Inputs a workflow cannot produce itself before they are needed."""
    simulated = set(available)
    missing: list[str] = []
    for step in definition.get("steps", []):
        for type_ in missing_agent_inputs(step.get("agent", ""), simulated):
            if type_ not in missing:
                missing.append(type_)
        simulated.update(AGENT_OUTPUTS.get(step.get("agent", ""), ()))
    return missing


class WorkflowRejected(Exception):
    def __init__(self, step: str, feedback: str):
        self.step = step
        self.feedback = feedback
        super().__init__(f"Rechazado en {step}" + (f": {feedback}" if feedback else ""))


class WorkflowState(TypedDict, total=False):
    payload: dict[str, Any]
    results: dict[str, Any]
    escalate: dict[str, Any] | None


MAX_REVISIONS = 2


def validate_definition(definition: dict) -> list[str]:
    """Returns a list of problems; empty list = valid."""
    problems: list[str] = []
    steps = definition.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["El workflow debe tener al menos un paso"]
    available = {"course_idea_brief"}
    seen: set[str] = set()
    for i, step in enumerate(steps):
        agent = step.get("agent")
        if agent not in VALID_AGENTS:
            problems.append(f"Paso {i + 1}: agente inválido '{agent}'")
            continue
        if i == 0 and agent != "curator":
            problems.append("Paso 1: el workflow debe empezar por Curador")
        if agent in seen:
            problems.append(f"Paso {i + 1}: el agente '{agent}' ya est\u00e1 incluido")
        missing = set(AGENT_INPUTS[agent]) - available
        if missing:
            names = ", ".join(sorted(missing))
            problems.append(
                f"Paso {i + 1}: '{agent}' necesita artefactos que a\u00fan no existen: {names}"
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


def build_workflow_graph(
    definition: dict, job_id: str, handlers: dict, append_event, evaluator=None
):
    """Compile the declarative chain into a LangGraph StateGraph.

    evaluator(agent, result) -> (verdict, feedback) is injected by the
    runner; steps with evaluate=true get a judge + bounded revise loop and
    a human-escalation node when revisions run out.
    """
    graph: StateGraph = StateGraph(WorkflowState)
    steps = definition["steps"]
    previous = START

    for i, step in enumerate(steps):
        agent = step["agent"]
        node_name = f"step{i + 1}_{agent}"

        def make_agent_node(step=step, agent=agent, index=i):
            def node(state: WorkflowState) -> WorkflowState:
                append_event(
                    job_id,
                    "stage",
                    f"Paso {index + 1}: {agent} — iniciando",
                    {"agent": agent, "step": index + 1},
                )
                stage_payload = {**state["payload"], **step.get("overrides", {})}
                result = handlers[f"{agent}_run"](job_id, stage_payload)
                results = {**state.get("results", {}), agent: result}
                return {"results": results}

            return node

        graph.add_node(node_name, make_agent_node())
        graph.add_edge(previous, node_name)
        previous = node_name

        if step.get("evaluate") and evaluator is not None:
            eval_name = f"eval{i + 1}_{agent}"
            escalate_name = f"escalate{i + 1}_{agent}"

            def make_eval_node(step=step, agent=agent, index=i):
                def node(state: WorkflowState) -> WorkflowState:
                    results = dict(state.get("results", {}))
                    stage_payload = {**state["payload"], **step.get("overrides", {})}
                    attempts = 0
                    while True:
                        verdict, feedback = evaluator(agent, results.get(agent))
                        if verdict == "pass":
                            return {"results": results, "escalate": None}
                        if attempts >= MAX_REVISIONS:
                            return {
                                "results": results,
                                "escalate": {
                                    "step": index + 1,
                                    "agent": agent,
                                    "type": "evaluation",
                                    "feedback": feedback,
                                },
                            }
                        attempts += 1
                        append_event(
                            job_id,
                            "stage",
                            f"Revisión {attempts}/{MAX_REVISIONS} de {agent} "
                            f"con feedback del evaluador…",
                        )
                        results[agent] = handlers[f"{agent}_run"](
                            job_id,
                            {**stage_payload, "revision_feedback": feedback},
                        )

                return node

            # Escalation lives in its own node (interrupt must not share a
            # node with expensive work) and no-ops when there is nothing
            # to escalate, keeping the graph linear.
            def make_escalate_node(agent=agent, index=i):
                def node(state: WorkflowState) -> WorkflowState:
                    info = state.get("escalate")
                    if not info:
                        return {}
                    decision = interrupt(info)
                    if not (decision or {}).get("approved", False):
                        raise WorkflowRejected(
                            f"paso {index + 1} ({agent}, evaluación)",
                            (decision or {}).get("feedback", ""),
                        )
                    return {"escalate": None}

                return node

            graph.add_node(eval_name, make_eval_node())
            graph.add_edge(previous, eval_name)
            graph.add_node(escalate_name, make_escalate_node())
            graph.add_edge(eval_name, escalate_name)
            previous = escalate_name

        if step.get("approval_after"):
            approval_name = f"approval{i + 1}_{agent}"

            # Approval lives in its own node: on resume LangGraph re-runs the
            # node from its start, so the expensive agent node must not share
            # a node with interrupt().
            def make_approval_node(agent=agent, index=i, approval_name=approval_name):
                def node(state: WorkflowState) -> WorkflowState:
                    decision = interrupt(
                        {
                            "step": index + 1,
                            "agent": agent,
                            "result": state.get("results", {}).get(agent),
                        }
                    )
                    if not (decision or {}).get("approved", False):
                        raise WorkflowRejected(
                            f"paso {index + 1} ({agent})",
                            (decision or {}).get("feedback", ""),
                        )
                    return {}

                return node

            graph.add_node(approval_name, make_approval_node())
            graph.add_edge(previous, approval_name)
            previous = approval_name

    graph.add_edge(previous, END)
    return graph
