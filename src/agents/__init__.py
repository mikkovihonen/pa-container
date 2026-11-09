from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from agents.antigravity_driver import AntigravityDriver
from agents.base import AgentDriver, AgentMount, T3DriverMetadata
from agents.claude_driver import ClaudeDriver
from agents.opencode_driver import OpenCodeDriver
from agents.pi_driver import PiAgentDriver
from agents.synthesis import (
    extract_models_from_yaml,
    load_project_models,
)
from agents.t3 import synthesize_t3_policy, synthesize_t3_settings

"""Coding agent abstractions and runtime drivers."""

AVAILABLE_AGENTS: tuple[str, ...] = ("pi", "opencode", "antigravity", "claude")

_DRIVERS: dict[str, type[AgentDriver]] = {
    "pi": PiAgentDriver,
    "opencode": OpenCodeDriver,
    "antigravity": AntigravityDriver,
    "claude": ClaudeDriver,
}


def get_agent_driver(name: str) -> AgentDriver:
    """Resolve and return an AgentDriver instance for the specified agent name."""
    if not name or not isinstance(name, str):
        valid_agents = ", ".join(AVAILABLE_AGENTS)
        raise ValueError(f"Agent name is required. Supported agents: {valid_agents}")
    agent_key = name.strip().lower()
    driver_cls = _DRIVERS.get(agent_key)
    if driver_cls is None:
        valid_agents = ", ".join(AVAILABLE_AGENTS)
        raise ValueError(f"Unknown agent type: {name!r}. Supported agents: {valid_agents}")
    return driver_cls()


def resolve_selected_agent_names(
    cli_agent: str | None,
    enabled_agents: list[str],
    default_agent: str,
    is_t3_mode: bool,
) -> tuple[str, list[str]]:
    """Resolve the active agent name and full list of selected agent names.

    Args:
        cli_agent: CLI --agent flag argument (None, single agent, comma-separated list, or 'all').
        enabled_agents: List of agents enabled in this workspace config (agents.enabled).
        default_agent: Workspace default agent (agents.default).
        is_t3_mode: Whether T3 Code web mode is enabled.

    Returns:
        A tuple of (active_agent_name, list_of_selected_agent_names).
    """
    if cli_agent is None:
        if is_t3_mode:
            active = default_agent if default_agent in enabled_agents else enabled_agents[0]
            return active, list(enabled_agents)
        return default_agent, [default_agent]

    raw = cli_agent.strip().lower()
    if raw == "all":
        active = default_agent if default_agent in enabled_agents else enabled_agents[0]
        return active, list(enabled_agents)

    items = [x.strip().lower() for x in raw.split(",") if x.strip()]
    if not items:
        raise ValueError("Invalid empty --agent value specified.")

    valid_agents_str = ", ".join(AVAILABLE_AGENTS)
    enabled_agents_str = ", ".join(enabled_agents)

    selected: list[str] = []
    for item in items:
        if item not in AVAILABLE_AGENTS:
            raise ValueError(f"Unknown agent: {item!r}. Supported agents: {valid_agents_str}")
        if item not in enabled_agents:
            raise ValueError(
                f"Agent {item!r} is not enabled in this workspace's .pa-container/config.yaml. "
                f"Enabled agents: {enabled_agents_str}"
            )
        if item not in selected:
            selected.append(item)

    active = selected[0]
    return active, selected


__all__ = [
    "AVAILABLE_AGENTS",
    "AgentDriver",
    "AgentMount",
    "AntigravityDriver",
    "ClaudeDriver",
    "OpenCodeDriver",
    "PiAgentDriver",
    "T3DriverMetadata",
    "extract_models_from_yaml",
    "get_agent_driver",
    "load_project_models",
    "resolve_selected_agent_names",
    "synthesize_t3_policy",
    "synthesize_t3_settings",
]
