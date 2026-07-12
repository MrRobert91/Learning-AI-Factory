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

VALID_AGENTS = ("curator", "planner", "lessons", "slides")


class WorkflowRejected(Exception):
    def __init__(self, step: str, feedback: str):
        self.step = step
        self.feedback = feedback
        super().__init__(f"Rechazado en {step}" + (f": {feedback}" if feedback else ""))


class WorkflowState(TypedDict, total=False):
    payload: dict[str, Any]
    results: dict[str, Any]


def validate_definition(definition: dict) -> list[str]:
    """Returns a list of problems; empty list = valid."""
    problems: list[str] = []
    steps = definition.get("steps")
    if not isinstance(steps, list) or not steps:
        return ["El workflow debe tener al menos un paso"]
    for i, step in enumerate(steps):
        agent = step.get("agent")
        if agent not in VALID_AGENTS:
            problems.append(f"Paso {i + 1}: agente inválido '{agent}'")
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


def build_workflow_graph(definition: dict, job_id: str, handlers: dict, append_event):
    """Compile the declarative chain into a LangGraph StateGraph."""
    graph: StateGraph = StateGraph(WorkflowState)
    steps = definition["steps"]
    previous = START

    for i, step in enumerate(steps):
        agent = step["agent"]
        node_name = f"step{i + 1}_{agent}"

        def make_agent_node(step=step, agent=agent, index=i):
            def node(state: WorkflowState) -> WorkflowState:
                append_event(
                    job_id, "stage", f"Paso {index + 1}: {agent} — iniciando"
                )
                stage_payload = {**state["payload"], **step.get("overrides", {})}
                result = handlers[f"{agent}_run"](job_id, stage_payload)
                results = {**state.get("results", {}), agent: result}
                return {"results": results}

            return node

        graph.add_node(node_name, make_agent_node())
        graph.add_edge(previous, node_name)
        previous = node_name

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
