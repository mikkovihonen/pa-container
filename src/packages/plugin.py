from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from agents.base import AgentDriver, AgentMount
    from cli import RunOptions
    from config_types import ProjectConfig
    from packages.manifest import PackageManifest

sys.dont_write_bytecode = True


@dataclass
class ContainerRunSpec:
    """Mutable container launch arguments assembled by core and mutated by plugins."""

    env: dict[str, str] = field(default_factory=dict)
    mounts: list[AgentMount] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)
    cap_add: list[str] = field(default_factory=list)
    sysctl: dict[str, str] = field(default_factory=dict)
    ports: list[str] = field(default_factory=list)
    extra_run_args: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunContext:
    """Immutable execution context provided to ACP lifecycle hooks."""

    project_dir: Path
    container_name: str
    network_name: str
    proxy_url: str | None
    is_t3_mode: bool
    options: RunOptions
    config: ProjectConfig
    runtime: str = "podman"
    active_packages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SecretTokenMapping:
    """Explicit mapping from host OS keyring to in-container placeholder and proxy token replacer."""

    name: str
    keyring_account: str
    placeholder: str
    hosts: tuple[str, ...]
    keyring_service: str = "pa-container"
    header: str | None = None
    pattern: str | None = None
    json_path: str | None = None
    required: bool = True


class ACPPlugin:
    """Base interface for host-side ACP dynamic plugins."""

    def __init__(self, manifest: PackageManifest, package_dir: Path, project_dir: Path | None) -> None:
        self.manifest = manifest
        self.package_dir = package_dir
        self.host_dir = package_dir / "host"
        self.container_dir = package_dir / "container"
        self.project_dir = project_dir

    def register_cli_commands(self, subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
        """Register subcommands contributed by this package."""
        pass

    def register_cli_flags(self, run_parser: argparse.ArgumentParser) -> None:
        """Register CLI argument flags contributed by this package."""
        pass

    def contribute_config_schema(self) -> type[object] | None:
        """Return the dataclass or schema type for validating the package config section."""
        return None

    def get_secret_mappings(self, config: ProjectConfig) -> list[SecretTokenMapping]:
        """Contribute secret mappings linking OS keyring credentials to proxy token replacer rules."""
        return []

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        config: ProjectConfig,
        options: RunOptions,
    ) -> None:
        """Inject container runtime arguments (mounts, env vars, ports, capabilities, devices)."""
        pass

    def pre_start(self, context: RunContext) -> None:
        """Execute pre-container initialization (e.g. file synthesis, pre-flight checks)."""
        pass

    def post_start(self, context: RunContext) -> None:
        """Execute post-container initialization (e.g. tunnel establishment, browser launch)."""
        pass

    def on_stop(self, context: RunContext) -> None:
        """Clean up resources on container shutdown or failure."""
        pass


class ACPAgentPlugin(ACPPlugin, ABC):
    """Abstract interface for packages with category 'agents'."""

    @abstractmethod
    def get_agent_driver(self) -> AgentDriver:
        """Instantiate and return the AgentDriver."""
        raise NotImplementedError
