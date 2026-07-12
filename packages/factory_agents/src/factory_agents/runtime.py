"""Agent runtime: definitions, profile-composed prompts and deep-agent runs.

Every agent in the factory is described by an AgentSpec (code-owned) and
configured by a profile (user-owned: soul.md + agents.md + config). The
final system prompt is composed as base_prompt + agents.md + soul.md, in
that order — the base prompt sets boundaries a profile cannot override.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from factory_agents.llm import get_chat_model


@dataclass(frozen=True)
class AgentSpec:
    name: str
    display_name: str
    description: str
    base_prompt: str
    tool_names: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    default_soul_md: str = ""
    default_agents_md: str = ""
    # Conversational agents (ideation) run in-request; task agents run as jobs.
    kind: str = "task"


@dataclass
class RunEvent:
    """Progress event emitted while a task agent runs."""

    type: str  # tool_call | assistant | result | error
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)


REGISTRY: dict[str, AgentSpec] = {}


def register(spec: AgentSpec) -> AgentSpec:
    REGISTRY[spec.name] = spec
    return spec


def get_spec(name: str) -> AgentSpec:
    if name not in REGISTRY:
        raise KeyError(f"Agente desconocido: {name}")
    return REGISTRY[name]


def compose_system_prompt(spec: AgentSpec, soul_md: str = "", agents_md: str = "") -> str:
    parts = [spec.base_prompt.strip()]
    if agents_md.strip():
        parts.append("# Instrucciones operativas (agents.md)\n\n" + agents_md.strip())
    if soul_md.strip():
        parts.append("# Personalidad y criterio (soul.md)\n\n" + soul_md.strip())
    return "\n\n".join(parts)


def _summarize_message(message: Any) -> list[RunEvent]:
    """Map a LangChain message from the agent stream to progress events."""
    events: list[RunEvent] = []
    tool_calls = getattr(message, "tool_calls", None) or []
    for tc in tool_calls:
        args = tc.get("args", {})
        arg_preview = ", ".join(f"{k}={str(v)[:80]}" for k, v in list(args.items())[:3])
        events.append(
            RunEvent(
                type="tool_call",
                summary=f"{tc.get('name', '?')}({arg_preview})",
                data={"tool": tc.get("name", "?")},
            )
        )
    content = getattr(message, "content", None)
    msg_type = getattr(message, "type", "")
    if content and msg_type == "ai" and not tool_calls:
        text = content if isinstance(content, str) else str(content)
        events.append(RunEvent(type="assistant", summary=text[:400]))
    return events


def run_task_agent(
    spec: AgentSpec,
    task_input: str,
    *,
    model: str,
    api_key: str,
    workspace_dir: str | Path,
    soul_md: str = "",
    agents_md: str = "",
    tools: list[Any] | None = None,
    recursion_limit: int = 80,
) -> Iterator[RunEvent]:
    """Run a task agent to completion, yielding progress events.

    The final event has type="result" with the agent's answer in summary.
    """
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend

    workspace = Path(workspace_dir)
    workspace.mkdir(parents=True, exist_ok=True)

    agent = create_deep_agent(
        model=get_chat_model(model, api_key),
        tools=tools or [],
        system_prompt=compose_system_prompt(spec, soul_md, agents_md),
        backend=FilesystemBackend(root_dir=workspace, virtual_mode=True),
    )

    final_text = ""
    for update in agent.stream(
        {"messages": [{"role": "user", "content": task_input}]},
        stream_mode="updates",
        config={"recursion_limit": recursion_limit},
    ):
        for node_output in update.values():
            if not isinstance(node_output, dict):
                continue
            for message in node_output.get("messages", []) or []:
                yield from _summarize_message(message)
                if getattr(message, "type", "") == "ai":
                    content = getattr(message, "content", "")
                    if isinstance(content, str) and content.strip():
                        final_text = content

    yield RunEvent(type="result", summary=final_text)
