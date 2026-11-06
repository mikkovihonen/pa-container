from __future__ import annotations

import sys

sys.dont_write_bytecode = True

from agents.antigravity_driver import AntigravityDriver
from agents.base import AgentDriver, AgentMount
from agents.claude_driver import ClaudeDriver
from agents.opencode_driver import OpenCodeDriver
from agents.pi_driver import PiAgentDriver
from agents.synthesis import (
    extract_models_from_yaml,
    load_project_models,
    resolve_models_file,
)

"""Coding agent abstractions and runtime drivers."""

AVAILABLE_AGENTS: tuple[str, ...] = ("pi", "opencode", "antigravity", "claude")

_DRIVERS: dict[str, type[AgentDriver]] = {
    "pi": PiAgentDriver,
    "default": PiAgentDriver,
    "opencode": OpenCodeDriver,
    "open-code": OpenCodeDriver,
    "antigravity": AntigravityDriver,
    "agy": AntigravityDriver,
    "claude": ClaudeDriver,
    "claude-code": ClaudeDriver,
}


def get_agent_driver(name: str | None = None) -> AgentDriver:
    """Resolve and return an AgentDriver instance for the specified agent name."""
    agent_key = (name or "pi").strip().lower()
    driver_cls = _DRIVERS.get(agent_key)
    if driver_cls is None:
        valid_agents = ", ".join(AVAILABLE_AGENTS)
        raise ValueError(f"Unknown agent type: {name!r}. Supported agents: {valid_agents}")
    return driver_cls()


__all__ = [
    "AVAILABLE_AGENTS",
    "AgentDriver",
    "AgentMount",
    "AntigravityDriver",
    "ClaudeDriver",
    "OpenCodeDriver",
    "PiAgentDriver",
    "extract_models_from_yaml",
    "get_agent_driver",
    "load_project_models",
    "resolve_models_file",
]
