from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from factory_schema import AgentSpec, FactoryConfig


class FactoryBackend(ABC):
    """Abstract runtime provider for managing a Software Factory environment."""

    @abstractmethod
    def start_proxy(self, config: FactoryConfig) -> str:
        """Start external coding-agent-proxy listening on all configured agent ports.

        Returns:
            The IP address of the host where the proxy is listening.
        """

    @abstractmethod
    def ensure_factory_vm(self, config: FactoryConfig, proxy_ip: str) -> None:
        """Boot or update the Factory VM (Tart or Incus) with hypervisor network lock."""

    @abstractmethod
    def sync_git_to_vault(self, host_repo: Path, branch: str = "HEAD") -> str:
        """Push host Git state into the Factory VM's /var/pa-vault bare repository.

        Returns:
            The commit hash synced into the vault.
        """

    @abstractmethod
    def launch_agent(self, agent: AgentSpec, task_prompt: str | None = None) -> int:
        """Instruct pa-agentd to create user/CoW clone, apply firewall/sandbox, and start agent.

        Returns:
            Exit code of the agent process or 0 if started in background.
        """

    @abstractmethod
    def fetch_agent_branch(self, agent_id: str, host_repo: Path) -> str:
        """Fetch agent's branch from Factory VM Vault into host .git and create review worktree.

        Returns:
            The path to the local git worktree created for review.
        """

    @abstractmethod
    def stop_factory(self) -> None:
        """Gracefully stop all agent sandboxes, shut down Factory VM, and release refcounts."""

    @abstractmethod
    def get_status(self) -> dict[str, object]:
        """Return operational status of VM, proxy, and active agents."""


def get_backend(config: FactoryConfig | None = None) -> FactoryBackend:
    """Select and instantiate the appropriate FactoryBackend based on platform and configuration."""
    from factory_schema import load_factory_config

    cfg = config if config is not None else load_factory_config()
    backend_type = cfg.compute.backend.lower()

    if backend_type == "auto":
        if sys.platform == "darwin":
            from backends.tart_macos import TartMacOSBackend

            return TartMacOSBackend(config=cfg)
        else:
            from backends.incus_linux import IncusLinuxBackend

            return IncusLinuxBackend(config=cfg)
    elif backend_type in ("macos-tart", "tart"):
        from backends.tart_macos import TartMacOSBackend

        return TartMacOSBackend(config=cfg)
    elif backend_type in ("linux-incus", "incus"):
        from backends.incus_linux import IncusLinuxBackend

        return IncusLinuxBackend(config=cfg)
    else:
        raise ValueError(f"Unsupported compute backend: {backend_type!r}")
