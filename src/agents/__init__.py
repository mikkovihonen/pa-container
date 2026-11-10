from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

sys.dont_write_bytecode = True

from agents.base import AgentDriver, AgentMount, T3DriverMetadata
from agents.synthesis import (
    extract_models_from_yaml,
    load_project_models,
)
from packages.discovery import discover_packages, get_package_dir
from packages.loader import load_acp_plugin
from packages.manifest import load_package_manifest
from packages.plugin import ACPAgentPlugin

"""Coding agent abstractions and runtime drivers."""

_LOADED_AGENT_DRIVERS: dict[str, AgentDriver] = {}


def discover_available_agents(repo_root: Path | None = None) -> dict[str, str]:
    """Map agent name to package name for all packages with category 'agents'."""
    manifests = discover_packages(repo_root=repo_root)
    agent_map: dict[str, str] = {}
    for pkg_name, manifest in manifests.items():
        if manifest.category == "agents":
            agent_map[pkg_name] = pkg_name
    return agent_map


AVAILABLE_AGENTS: tuple[str, ...] = ("antigravity", "claude-code", "opencode", "pi")


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
    pkg_name = agent_map.get(agent_key)
    if not pkg_name:
        valid = ", ".join(sorted(agent_map.keys()))
        raise ValueError(f"Unknown agent type: {name!r}. Supported agents: {valid}")

    pkg_dir = get_package_dir(pkg_name, repo_root=repo_root)
    manifest_path = pkg_dir / "package.yaml"
    manifest = load_package_manifest(manifest_path)
    plugin = load_acp_plugin(manifest=manifest, package_dir=pkg_dir, project_dir=project_dir)
    if not isinstance(plugin, ACPAgentPlugin):
        raise TypeError(f"Package '{pkg_name}' does not implement ACPAgentPlugin")

    driver = plugin.get_agent_driver()
    _LOADED_AGENT_DRIVERS[agent_key] = driver
    return driver


def resolve_selected_agent_names(
    cli_agent: str | None,
    enabled_agents: list[str],
    default_agent: str,
    is_t3_mode: bool,
    repo_root: Path | None = None,
) -> tuple[str, list[str]]:
    """Resolve the active agent name and full list of selected agent names.

    Args:
        cli_agent: CLI --agent flag argument (None, single agent, comma-separated list, or 'all').
        enabled_agents: List of agents enabled in this workspace config.
        default_agent: Workspace default agent.
        is_t3_mode: Whether T3 Code web mode is enabled.
        repo_root: Optional repository root path.

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
    "AgentDriver",
    "AgentMount",
    "T3DriverMetadata",
    "discover_available_agents",
    "extract_models_from_yaml",
    "get_agent_driver",
    "load_project_models",
    "resolve_selected_agent_names",
]
