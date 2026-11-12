from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from .base import AgentDriver

sys.dont_write_bytecode = True

from packages.discovery import get_package_dir
from packages.manifest import load_package_manifest

from .drivers import AntigravityDriver, ClaudeDriver, OpenCodeDriver, PiAgentDriver

"""Registry and resolution for AI coding agents."""

AVAILABLE_AGENTS: tuple[str, ...] = ("antigravity", "claude", "opencode", "pi")

DRIVER_CLASSES: dict[str, type[AgentDriver]] = {
    "antigravity": AntigravityDriver,
    "claude": ClaudeDriver,
    "opencode": OpenCodeDriver,
    "pi": PiAgentDriver,
}

_LOADED_AGENT_DRIVERS: dict[str, AgentDriver] = {}


def discover_available_agents(repo_root: Path | None = None) -> dict[str, str]:
    """Map agent feature name to package name ('agents') for all available agent features."""
    try:
        pkg_dir = get_package_dir("agents", repo_root=repo_root)
        manifest = load_package_manifest(pkg_dir / "package.yaml")
        if manifest.features:
            return dict.fromkeys(sorted(manifest.features.keys()), "agents")
    except Exception:
        pass
    return dict.fromkeys(AVAILABLE_AGENTS, "agents")


def get_agent_driver(
    name: str,
    repo_root: Path | None = None,
    project_dir: Path | None = None,
) -> AgentDriver:
    """Resolve and return an AgentDriver instance for the specified agent name."""
    if not name or not isinstance(name, str):
        agent_map = discover_available_agents(repo_root)
        valid = ", ".join(sorted(agent_map.keys()))
        raise ValueError(f"Agent name is required. Supported agents: {valid}")

    agent_key = name.strip().lower()
    if agent_key in _LOADED_AGENT_DRIVERS:
        return _LOADED_AGENT_DRIVERS[agent_key]

    agent_map = discover_available_agents(repo_root)
    if agent_key not in agent_map or agent_key not in DRIVER_CLASSES:
        valid = ", ".join(sorted(agent_map.keys()))
        raise ValueError(f"Unknown agent type: {name!r}. Supported agents: {valid}")

    driver = DRIVER_CLASSES[agent_key]()
    _LOADED_AGENT_DRIVERS[agent_key] = driver
    return driver


def resolve_selected_agent_names(
    cli_agent: str | None,
    enabled_agents: list[str],
    default_agent: str,
    multi_agent: bool = False,
    repo_root: Path | None = None,
) -> tuple[str, list[str]]:
    """Resolve the active agent name and full list of selected agent names.

    Args:
        cli_agent: CLI --agent flag argument (None, single agent, comma-separated list, or 'all').
        enabled_agents: List of agents enabled in this workspace config.
        default_agent: Workspace default agent.
        multi_agent: Whether multi-agent orchestration mode is enabled.
        repo_root: Optional repository root path.

    Returns:
        A tuple of (active_agent_name, list_of_selected_agent_names).
    """
    if cli_agent is None:
        if multi_agent:
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

    available = discover_available_agents(repo_root)
    valid_agents_str = ", ".join(sorted(available.keys()))
    enabled_agents_str = ", ".join(enabled_agents)

    selected: list[str] = []
    for item in items:
        if item not in available:
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
    "discover_available_agents",
    "get_agent_driver",
    "resolve_selected_agent_names",
]
