from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

sys.dont_write_bytecode = True

"""Base classes and data structures for coding agent runtime drivers."""


@dataclass(frozen=True)
class AgentMount:
    """Represents a host-to-container mount required by an agent."""

    source: Path
    destination: str
    read_only: bool = False

    def to_run_args(self) -> list[str]:
        """Convert mount to podman/docker run CLI arguments."""
        mode = ":ro" if self.read_only else ""
        return ["--volume", f"{self.source}:{self.destination}{mode}"]


class AgentDriver(ABC):
    """Abstract interface defining execution, mounting, and configuration contracts for agents."""

    @property
    @abstractmethod
    def name(self) -> str:
        """The canonical name identifying this agent (e.g. 'pi', 'opencode', 'antigravity', 'claude')."""
        ...

    @property
    def required_tools(self) -> list[str]:
        """List of on-demand builder tools required by this agent."""
        return []

    def get_command(self, cli_args: list[str]) -> list[str]:
        """Return the command arguments to execute inside the container."""
        return [self.name, *cli_args]

    def get_environment(self, config: dict | None = None) -> dict[str, str]:
        """Return dummy/placeholder environment variables needed by this agent."""
        return {}

    def get_mounts(self, project_dir: Path, agent_config_dir: Path) -> list[AgentMount]:
        """Return host-to-container mounts for agent-specific state and configs."""
        return []

    def get_tmpfs_paths(self) -> list[str]:
        """Return container paths to be mounted as volatile RAM disks."""
        return []

    def synthesize_config(
        self,
        server_configs: list[dict],
        gateway_configs: list[dict],
        default_model: str | None,
        project_dir: Path,
        agent_config_dir: Path,
    ) -> None:
        """Synthesize agent-specific configuration from active models and gateways."""
        return None

    def get_t3_driver(self) -> str | None:
        """Return the corresponding T3 Code driver name if supported, else None."""
        return None
