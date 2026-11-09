from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import AgentExtrasConfig, GatewayConfigItem, ServerConfigItem

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger

logger = get_category_logger(__name__, LogCategory.AGENT)

"""Base classes and data structures for coding agent runtime drivers."""


@dataclass(frozen=True)
class AgentMount:
    """Represents a host-to-container mount required by an agent."""

    source: Path
    destination: str
    read_only: bool = False

    def to_run_args(self) -> list[str]:
        """Convert mount to podman run CLI arguments."""
        mode = ":ro" if self.read_only else ""
        return ["--volume", f"{self.source}:{self.destination}{mode}"]


@dataclass(frozen=True)
class T3DriverMetadata:
    """T3 Code provider metadata and instance configuration."""

    driver_kind: str
    instance_id: str
    settings: dict[str, Any] = field(default_factory=dict)


class AgentDriver(ABC):
    """Abstract interface defining execution, mounting, and configuration contracts for agents."""

    @property
    @abstractmethod
    def name(self) -> str:
        """The canonical name identifying this agent (e.g. 'pi', 'opencode', 'antigravity', 'claude')."""
        ...

    @property
    def required_packages(self) -> list[str]:
        """List of Agent Capability Packages required by this agent."""
        return []

    def get_command(self, cli_args: list[str]) -> list[str]:
        """Return the command arguments to execute inside the container."""
        return [self.name, *cli_args]

    def get_environment(
        self,
        config: AgentExtrasConfig | None = None,
        gateway_configs: list[GatewayConfigItem] | None = None,
    ) -> dict[str, str]:
        """Return dummy/placeholder environment variables needed by this agent."""
        return {}

    def get_state_dir(self, project_dir: Path) -> Path:
        """Return host path for agent-specific state and configs."""
        return project_dir / ".pa-container" / "agents" / self.name

    def get_mounts(self, project_dir: Path) -> list[AgentMount]:
        """Return host-to-container mounts for agent-specific state and configs."""
        return []

    def get_shadow_paths(self) -> list[str]:
        """Return container paths to be shadowed into the project shadow volume."""
        return []

    def get_sessions_dir(self, project_dir: Path) -> Path | None:
        """Return host path where agent session files are stored, if applicable."""
        return self.get_state_dir(project_dir) / "sessions"

    def is_gateway_enabled_for_agent(self, gateway: GatewayConfigItem) -> bool:
        """Check if an external gateway is allowed for this agent.

        Gateways with auth.type == 'agent-native' are only enabled for their own agent.
        """
        gw_def = gateway.get("gatewayDef")
        if gw_def is None:
            return True
        auth = getattr(gw_def, "auth", None)
        if auth is None or getattr(auth, "type", None) != "agent-native":
            return True

        explicit_agent = getattr(gw_def, "agent", None)
        if explicit_agent and isinstance(explicit_agent, str) and explicit_agent.strip():
            return explicit_agent.strip().lower() == self.name

        gw_type = getattr(gw_def, "gateway_type", None) or ""
        gw_id = getattr(gw_def, "id", None) or gateway.get("name") or ""
        if gw_type == "anthropic" or gw_id in ("anthropic", "anthropic-account"):
            return self.name == "claude"
        if gw_type == "gemini" or gw_id in ("gemini", "google-account"):
            return self.name == "antigravity"
        if gw_type == "opencode" or gw_id == "opencode":
            return self.name == "opencode"
        if gw_type == "pi" or gw_id == "pi":
            return self.name == "pi"

        return False

    def synthesize_config(
        self,
        server_configs: list[ServerConfigItem],
        gateway_configs: list[GatewayConfigItem],
        default_model: str | None,
        project_dir: Path,
    ) -> None:
        """Synthesize agent-specific configuration from active models and gateways."""
        return None

    def get_package_mcp_servers(self, project_dir: Path) -> dict[str, dict[str, Any]]:
        """Retrieve aggregated MCP server configurations for packages active in project_dir."""
        try:
            from images import read_project_packages
            from packages import discover_packages, get_mcp_servers_dict

            active_pkgs = read_project_packages(project_dir, extra_packages=self.required_packages)
            all_manifests = discover_packages()
            active_manifests = [all_manifests[p] for p in active_pkgs if p in all_manifests]
            return get_mcp_servers_dict(active_manifests)
        except Exception as e:
            logger.debug(f"Failed to resolve package MCP servers: {e}")
            return {}

    def get_t3_metadata(self) -> T3DriverMetadata | None:
        """Return the T3 Code provider metadata and configuration if supported, else None."""
        return None
