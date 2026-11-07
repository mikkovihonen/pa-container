from __future__ import annotations

import sys

sys.dont_write_bytecode = True

"""Central type definitions for project configurations, synthesis models, and manifests.

Dedicated type module to provide pure data structures across the runtime without
introducing circular import dependencies.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from models import ServerConfig
    from registry import GatewayDef


class ClientInfo(TypedDict, total=False):
    """Manifest entry tracking a live client process."""

    pid: int
    run_id: str | None
    timestamp: str | float | None
    registered_at: str | None
    proxy_name: str | None
    container_name: str | None
    server_id: str | None


class TokenData(TypedDict, total=False):
    """OAuth2 token cache structure."""

    access_token: str
    token_type: str
    refresh_token: str
    expires_in: int | float
    expires_at: float
    scope: str


class ServerConfigItem(TypedDict):
    """Synthesized local llama-server configuration item."""

    name: str
    config: ServerConfig
    baseUrl: str


class GatewayConfigItem(TypedDict):
    """Synthesized external API gateway configuration item."""

    name: str
    gatewayDef: GatewayDef
    baseUrl: str


# ─── Project Configuration TypedDicts ────────────────────────────────────────


class ResourceLimits(TypedDict):
    """Container CPU and memory resource constraints."""

    memory: str | None
    cpus: int | float | str | None


class LlamaConfig(TypedDict):
    """Local llama-server startup and polling parameters."""

    startup_timeout: int
    startup_attempts: int


class NetworkConfig(TypedDict):
    """Networking configuration for container isolation."""

    ipv6: bool
    dns: str


class ProxyConfig(TypedDict):
    """Proxy parameters controlling UI exposure and stream limits."""

    expose_ui: str
    max_view_flows: int | None
    stream_large_bodies: str | None


class PortPublishConfig(TypedDict):
    """Port publishing and binding configuration."""

    expose: str
    publish: list[tuple[int, int]]


class NestedContainersConfig(TypedDict):
    """Nested container runtime engine settings."""

    enabled: bool
    storage: str
    security: str
    ports: PortPublishConfig


class AgentExtrasConfig(TypedDict):
    """Additional environment variables, mounts, capabilities, and devices."""

    env: dict[str, str]
    mounts: list[str]
    capabilities: list[str]
    devices: list[str]


class SecurityConfig(TypedDict):
    """Workspace and git security enforcement parameters."""

    read_only_git_hooks: bool
    blocked_mount_paths: list[str]
    blocked_ip_ranges: list[str]
    git_config_allowlist: list[str]


class SourceControlConfig(TypedDict):
    """Source control and git credential helper configuration."""

    enabled: bool
    auto_detect_host_cli: bool
    setup_git_credentials: bool
    providers: dict[str, object]


class ProjectConfig(TypedDict, total=False):
    """Top-level parsed representation of .pi-container/config.yaml."""

    schema_version: str
    resources: dict[str, ResourceLimits]
    llama: LlamaConfig
    network: NetworkConfig
    proxy: ProxyConfig
    nested_containers: NestedContainersConfig
    agent: AgentExtrasConfig
    security: SecurityConfig
    source_control: SourceControlConfig
    tools: dict[str, list[str]]
    egress: dict[str, object]
    tmpfs: dict[str, object]
    volumes: dict[str, object]
    flow_export: dict[str, object]
    git: dict[str, object]
    agents: dict[str, object]


# ─── Global Configuration (~/.config/pi-container/config.yaml) ────────────────


@dataclass(frozen=True)
class RuntimeGlobalConfig:
    """Runtime container engine and host networking parameters."""

    log_level: str = "INFO"
    bridge_interface: str | None = None
    proxy_upstream_network: str = "podman"


@dataclass(frozen=True)
class LlamaBuildGlobalConfig:
    """Source build settings for host-native llama-server."""

    repo: str = "https://github.com/ggml-org/llama.cpp.git"
    tag: str = "v0.9.0"
    backend: str = "auto"
    minimal: bool = True
    cmake_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LlamaGlobalConfig:
    """Local host llama-server binary and build configurations."""

    bin: str | None = None
    build: LlamaBuildGlobalConfig = field(default_factory=LlamaBuildGlobalConfig)


@dataclass(frozen=True)
class BuildImagesGlobalConfig:
    """Container image tags for local pi-container images."""

    agent: str = "pi-coding-agent:local"
    proxy: str = "pi-coding-agent-proxy:local"
    builder: str = "pi-coding-agent-builder:local"


@dataclass(frozen=True)
class BuildGlobalConfig:
    """Container image build settings and flags."""

    images: BuildImagesGlobalConfig = field(default_factory=BuildImagesGlobalConfig)
    dns: str = "1.1.1.1"
    python_optimize: bool = True
    memory_preflight: bool = True
    node_source: str = "prebuilt"
    prune_dangling: bool = True
    purge_build_cache: bool = False


@dataclass(frozen=True)
class GlobalConfig:
    """Top-level parsed representation of ~/.config/pi-container/config.yaml."""

    schema_version: str = "0.6.6"
    runtime: RuntimeGlobalConfig = field(default_factory=RuntimeGlobalConfig)
    llama: LlamaGlobalConfig = field(default_factory=LlamaGlobalConfig)
    build: BuildGlobalConfig = field(default_factory=BuildGlobalConfig)
