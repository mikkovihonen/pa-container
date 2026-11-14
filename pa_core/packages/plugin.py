from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    import argparse
    from contextlib import ExitStack
    from pathlib import Path

    from cli import RunOptions
    from config_types import ProjectConfig
    from packages.manifest import PackageManifest
sys.dont_write_bytecode = True


@dataclass(frozen=True)
class ContainerMount:
    """Represents a host-to-container mount."""

    source: Path
    destination: str
    read_only: bool = False

    def to_run_args(self) -> list[str]:
        """Convert mount to podman run CLI arguments."""
        mode = ":ro" if self.read_only else ""
        return ["--volume", f"{self.source}:{self.destination}{mode}"]


AgentMount = ContainerMount


class IngressAuthPolicy(StrEnum):
    """Authentication model provided by the backend service."""

    INTRINSIC = "intrinsic"
    """Service provides its own cryptographic or strong authentication (e.g. T3 pairing tokens).
    Can be safely exposed directly without an external auth gate."""

    REQUIRED = "required"
    """Service has no native authentication (e.g. noVNC, raw dev server, web terminal).
    Must be gated by an external Ingress Auth Gate when exposed publicly."""

    NONE = "none"
    """Service is intentionally unauthenticated and public (e.g. public static site demo).
    Bypasses the auth gate only if explicitly requested by the user."""


@dataclass(frozen=True)
class TunnelEndpointRequest:
    """Request from a package to expose a local service via tunnel."""

    service_name: str
    """Canonical identifier for the service (e.g. 't3', 'desktop', 'zellij')."""

    port: int
    """Local host port bound to 127.0.0.1 or 0.0.0.0."""

    protocol: str = "http"
    """Protocol type: 'http', 'websocket', or 'tcp'."""

    auth_policy: IngressAuthPolicy = IngressAuthPolicy.REQUIRED
    """Authentication policy required for this endpoint."""

    preferred_subdomain: str | None = None
    """Desired subdomain for named tunnels (e.g. 't3' for t3.domain.com)."""

    path_prefix: str | None = None
    """Subpath prefix if multiplexed behind a path router (e.g. '/desktop')."""

    title: str = ""
    """Human-readable display name for logging and terminal link banners."""


@dataclass
class TunnelEndpoint:
    """Active provisioned tunnel endpoint."""

    request: TunnelEndpointRequest
    public_url: str
    advertised_host: str
    is_gated: bool
    auth_mode: str = "none"
    access_token: str | None = None


@runtime_checkable
class TunnelProvider(Protocol):
    """Host-side tunnel provider interface."""

    def is_enabled(self) -> bool:
        """Whether tunneling has been activated via CLI or config."""
        ...

    def register_service(self, request: TunnelEndpointRequest) -> TunnelEndpoint | None:
        """Register a local service endpoint to be tunneled."""
        ...

    def get_endpoint(self, service_name: str) -> TunnelEndpoint | None:
        """Retrieve the provisioned endpoint for a service."""
        ...

    def provision_all(self, exit_stack: ExitStack) -> dict[str, TunnelEndpoint]:
        """Start all registered tunnels and auth gates, registering cleanup handlers."""
        ...


@dataclass
class ContainerRunSpec:
    """Mutable container launch arguments assembled by core and mutated by plugins."""

    env: dict[str, str] = field(default_factory=dict)
    mounts: list[ContainerMount] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)
    devices: list[str] = field(default_factory=list)
    cap_add: list[str] = field(default_factory=list)
    sysctl: dict[str, str] = field(default_factory=dict)
    ports: list[str] = field(default_factory=list)
    chown_paths: list[str] = field(default_factory=list)
    extra_run_args: list[str] = field(default_factory=list)


@dataclass
class RunContext:
    """Execution context provided to ACP lifecycle hooks."""

    project_dir: Path
    options: RunOptions
    config: ProjectConfig
    runtime: str = "podman"
    active_packages: list[str] = field(default_factory=list)
    container_name: str = ""
    network_name: str = ""
    proxy_url: str | None = None
    modes: set[str] = field(default_factory=set)
    attributes: dict[str, Any] = field(default_factory=dict)
    package_configs: dict[str, dict[str, Any]] = field(default_factory=dict)
    package_secrets: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    feature_configs: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    feature_secrets: dict[str, dict[str, list[dict[str, str]]]] = field(default_factory=dict)
    exit_stack: ExitStack | None = None

    def add_mode(self, mode: str) -> None:
        """Register an active operational mode (e.g. 't3', 'multi-agent')."""
        self.modes.add(mode)

    def has_mode(self, mode: str) -> bool:
        """Check if an operational mode is active."""
        return mode in self.modes

    def set_attribute(self, key: str, value: Any) -> None:
        """Store an arbitrary context attribute."""
        self.attributes[key] = value

    def get_attribute(self, key: str, default: Any = None) -> Any:
        """Retrieve an arbitrary context attribute."""
        return self.attributes.get(key, default)

    def get_package_config(self, package_name: str) -> dict[str, Any]:
        """Retrieve resolved configuration dictionary for a package."""
        return self.package_configs.get(package_name, {})

    def get_package_secrets(self, package_name: str) -> list[dict[str, str]]:
        """Retrieve explicit secret mappings for a package."""
        return self.package_secrets.get(package_name, [])

    def get_feature_config(self, package_name: str, feature_name: str) -> dict[str, Any]:
        """Retrieve resolved configuration dictionary for a feature within a package."""
        return self.feature_configs.get(package_name, {}).get(feature_name, {})

    def get_feature_secrets(self, package_name: str, feature_name: str) -> list[dict[str, str]]:
        """Retrieve explicit secret mappings for a feature within a package."""
        return self.feature_secrets.get(package_name, {}).get(feature_name, [])

    @property
    def tunnel_provider(self) -> TunnelProvider | None:
        """Retrieve active tunnel provider instance if registered."""
        prov = self.attributes.get("tunnel_provider")
        if prov is not None and (isinstance(prov, TunnelProvider) or hasattr(prov, "is_enabled")):
            return cast("TunnelProvider", prov)
        return None

    @tunnel_provider.setter
    def tunnel_provider(self, provider: TunnelProvider | None) -> None:
        """Set or clear active tunnel provider instance."""
        self.attributes["tunnel_provider"] = provider


class ACPPlugin:
    """Base interface for host-side ACP dynamic plugins."""

    def __init__(self, manifest: PackageManifest, package_dir: Path, project_dir: Path | None) -> None:
        self.manifest = manifest
        self.package_dir = package_dir
        self.host_dir = package_dir / "host"
        self.container_dir = package_dir / "container"
        self.project_dir = project_dir

    def register_cli_commands(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
        common_parser: argparse.ArgumentParser | None = None,
    ) -> None:
        """Register subcommands contributed by this package."""
        pass

    def register_cli_args(self, run_parser: argparse.ArgumentParser) -> None:
        """Register CLI argument flags contributed by this package."""
        pass

    def contribute_config_schema(self) -> type[object] | dict[str, Any] | None:
        """Return the dataclass or schema type/dict for validating the package config section."""
        return None

    def contribute_feature_config_schema(self, feature_name: str) -> type[object] | dict[str, Any] | None:
        """Return the dataclass or schema type/dict for validating a specific feature config section."""
        return None

    def on_run_init(self, context: RunContext) -> None:
        """Early initialization hook called right after RunContext is constructed."""
        pass

    def on_preflight(self, context: RunContext) -> None:
        """Preflight hook for verifying dependencies, single-instance locks, and preconditions."""
        pass

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        context: RunContext,
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
    def get_agent_driver(self) -> Any:
        """Instantiate and return the AgentDriver."""
        raise NotImplementedError
