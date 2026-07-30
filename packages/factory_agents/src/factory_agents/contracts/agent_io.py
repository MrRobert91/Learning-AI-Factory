"""Canonical agent input/output matrix shared with the web application."""

import json
from importlib.resources import files

_RAW_CONTRACTS = json.loads(
    files("factory_agents.contracts").joinpath("agent_io.json").read_text(encoding="utf-8")
)

AGENT_CONTRACTS: dict[str, dict[str, list[str] | str]] = _RAW_CONTRACTS
VALID_AGENTS = tuple(AGENT_CONTRACTS)
AGENT_INPUTS: dict[str, tuple[str, ...]] = {
    agent: tuple(contract["inputs"]) for agent, contract in AGENT_CONTRACTS.items()
}
AGENT_OUTPUTS: dict[str, tuple[str, ...]] = {
    agent: tuple(contract["outputs"]) for agent, contract in AGENT_CONTRACTS.items()
}
AGENT_NAMES: dict[str, str] = {
    agent: str(contract["name"]) for agent, contract in AGENT_CONTRACTS.items()
}
