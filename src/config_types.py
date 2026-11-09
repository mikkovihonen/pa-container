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


class GatewayConfigItem(TypedDict, total=False):
    """Synthesized external API gateway configuration item."""

    name: str
    gatewayDef: GatewayDef
    baseUrl: str
    containerEnvVar: str
    keyringService: str
    keyringAccount: str


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
    open_browser: bool


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


class LogRetentionConfig(TypedDict, total=False):
    """Log retention settings."""

    max_days: int | None
    max_launches: int | None


class LoggingProjectConfig(TypedDict, total=False):
    """Per-project logging configuration."""

    log_level: str | None
    retention: LogRetentionConfig


class DesktopEndpointConfig(TypedDict, total=False):
    """Configuration for a virtual desktop network endpoint (VNC or noVNC)."""

    enabled: bool
    port: int | str
    expose: str


class DesktopGpuConfig(TypedDict, total=False):
    """Configuration for virtual desktop graphics acceleration."""

    enabled: bool | str


class DesktopConfig(TypedDict, total=False):
    """Headless Wayland desktop and GUI application configuration."""

    enabled: bool
    resolution: str
    compositor: str
    vnc: DesktopEndpointConfig
    novnc: DesktopEndpointConfig
    open_browser: bool
    gpu: DesktopGpuConfig


class ProjectAgentsConfig(TypedDict, total=False):
    """Configuration for enabled agents and default agent."""

    enabled: list[str]
    default: str


class ProjectToolsConfig(TypedDict, total=False):
    """Optional tools configuration."""

    include: list[str]


class ProjectGitConfig(TypedDict, total=False):
    """Project-level git safety configuration."""

    safe_directory: bool
    rewrite_ssh_to_https: bool


class ProjectFlowExportConfig(TypedDict, total=False):
    """Flow export addon configuration."""

    enabled: bool


class ProjectEgressConfig(TypedDict, total=False):
    """Egress policy configuration."""

    allow: dict[str, object]


class ProjectTmpfsConfig(TypedDict, total=False):
    """Tmpfs mounts configuration."""

    paths: list[str]


class ProjectVolumesConfig(TypedDict, total=False):
    """Named volume mounts configuration."""

    paths: list[str]


class ProjectAgentSectionConfig(TypedDict, total=False):
    """Configuration section for the agent in .pa-container/config.yaml."""

    type: str
    command: list[str] | str | None
    options: dict[str, object]
    env: dict[str, str]
    mounts: list[str]
    capabilities: list[str]
    devices: list[str]
    read_only_pa_container: bool
    mode: str
    ports: dict[str, object]


class ProjectConfig(TypedDict, total=False):
    """Top-level parsed representation of .pa-container/config.yaml."""

    schema_version: str
    resources: dict[str, ResourceLimits]
    llama: LlamaConfig
    network: NetworkConfig
    proxy: ProxyConfig
    nested_containers: NestedContainersConfig
    agent: ProjectAgentSectionConfig
    security: SecurityConfig
    source_control: SourceControlConfig
    packages: list[str]
    egress: ProjectEgressConfig
    tmpfs: ProjectTmpfsConfig
    volumes: ProjectVolumesConfig
    flow_export: ProjectFlowExportConfig
    git: ProjectGitConfig
    agents: ProjectAgentsConfig
    logging: LoggingProjectConfig
    desktop: DesktopConfig


# ─── Global Configuration (~/.config/pa-container/config.yaml) ────────────────


@dataclass(frozen=True)
class LogRetentionGlobalConfig:
    """Retention parameters for host-wide and per-project logs."""

    max_days: int | None = 14
    max_launches: int | None = 10


@dataclass(frozen=True)
class LoggingGlobalConfig:
    """Logging settings in ~/.config/pa-container/config.yaml."""

    log_level: str = "INFO"
    retention: LogRetentionGlobalConfig = field(default_factory=LogRetentionGlobalConfig)


@dataclass(frozen=True)
class RuntimeGlobalConfig:
    """Runtime container engine and host networking parameters."""

    log_level: str = "INFO"
    proxy_upstream_network: str = "podman"
    open_browser: bool = False


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
    """Container image tags for local pa-container images."""

    agent: str = "pa-container-agent:local"
    proxy: str = "pa-container-agent-proxy:local"
    base: str = "pa-container-agent-base:local"
    builder: str = "pa-container-agent-base:local"


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
    """Top-level parsed representation of ~/.config/pa-container/config.yaml."""

    schema_version: str
    runtime: RuntimeGlobalConfig = field(default_factory=RuntimeGlobalConfig)
    llama: LlamaGlobalConfig = field(default_factory=LlamaGlobalConfig)
    build: BuildGlobalConfig = field(default_factory=BuildGlobalConfig)
    logging: LoggingGlobalConfig = field(default_factory=LoggingGlobalConfig)
