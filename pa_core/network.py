from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

sys.dont_write_bytecode = True

"""Container network and proxy container lifecycle management."""

from config import PROJECT_DIR, PROXY_LOCK_DIR
from runtimes import PodmanRuntime
from util import (
    get_free_port,
    get_ref_count,
    is_port_available,
    read_live_clients,
    run_quiet,
    start_refcounted_resource,
    stop_refcounted_resource,
)

if TYPE_CHECKING:
    import types
    from collections.abc import Mapping

    from config_types import (
        AgentExtrasConfig,
        ClientInfo,
        GatewayConfigItem,
        LlamaConfig,
        LoggingProjectConfig,
        LogRetentionConfig,
        NestedContainersConfig,
        NetworkConfig,
        PortPublishConfig,
        ProjectAgentSectionConfig,
        ProjectConfig,
        ProxyConfig,
        ResourceLimits,
    )
from logging_driver import LogCategory, get_category_logger

logger = get_category_logger(__name__, LogCategory.NETWORK)


# ─── Project config (.pa-container/config.yaml) ───────────────────────────

# Proxy egress policy: YAML key under ``egress.allow`` → the ``PROXY_ALLOW_*``
# env var the proxy entrypoint reads to open that protocol's (uninspected) rule.
_PROXY_FORWARD_FLAGS = {
    "ssh": "PROXY_ALLOW_SSH",
    "smtp": "PROXY_ALLOW_SMTP",
    "git": "PROXY_ALLOW_GIT",
    "ntp": "PROXY_ALLOW_NTP",
}
_PROXY_FORWARD_PORTS = {
    "tcp_ports": "PROXY_ALLOW_TCP_PORTS",
    "udp_ports": "PROXY_ALLOW_UDP_PORTS",
}


def load_project_config(config_dir: Path | None = None) -> ProjectConfig:
    """Load and parse `.pa-container/config.yaml`, failing hard if missing or invalid."""
    from yaml_strict import load_yaml_file

    config_path = (config_dir or (PROJECT_DIR / ".pa-container")) / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Project config not found at {config_path}")

    try:
        loaded = load_yaml_file(config_path)
    except Exception as e:
        raise ValueError(f"Invalid YAML in project config at {config_path}: {e}") from e
    if not isinstance(loaded, dict):
        raise ValueError(f"Project config at {config_path} must be a YAML mapping")
    return cast("ProjectConfig", loaded)


def scan_tmpfs_paths(config_dir: Path | None = None) -> list[str]:
    """Extract sorted list of container tmpfs mount paths from config.yaml `tmpfs.paths`."""
    tmpfs = load_project_config(config_dir).get("tmpfs") or {}
    paths = tmpfs.get("paths", []) or []
    return sorted({str(p) for p in paths})


def scan_volume_paths(config_dir: Path | None = None) -> list[str]:
    """Extract sorted list of container volume paths from config.yaml `volumes.paths`."""
    volumes = load_project_config(config_dir).get("volumes") or {}
    paths = volumes.get("paths", []) or []
    return sorted({str(p) for p in paths})


def read_flow_export_enabled(config_dir: Path | None = None) -> bool:
    """Read the proxy flow export toggle from config.yaml `flow_export.enabled`."""
    flow_export = load_project_config(config_dir).get("flow_export")
    if not isinstance(flow_export, dict) or "enabled" not in flow_export:
        raise ValueError("Missing required 'flow_export.enabled' configuration in project config")
    val = flow_export["enabled"]
    if not isinstance(val, bool):
        raise ValueError(f"Invalid 'flow_export.enabled': expected bool, got {type(val).__name__}")
    return val


def read_proxy_forward_env(config_dir: Path | None = None) -> dict[str, str]:
    """Generate `PROXY_ALLOW_*` environment variables for non-HTTP egress from config.yaml `egress.allow`."""
    egress = load_project_config(config_dir).get("egress")
    if not isinstance(egress, dict) or "allow" not in egress:
        raise ValueError("Missing required 'egress.allow' configuration in project config")
    allow = egress["allow"] or {}
    env: dict[str, str] = {}
    for key, var in _PROXY_FORWARD_FLAGS.items():
        if allow.get(key) is True:
            env[var] = "true"
    for key, var in _PROXY_FORWARD_PORTS.items():
        ports = allow.get(key)
        if isinstance(ports, str):
            joined = ports.strip()
        elif isinstance(ports, (list, tuple)):
            joined = ",".join(str(p).strip() for p in ports if str(p).strip())
        else:
            joined = ""
        if joined:
            env[var] = joined
    return env


def read_resource_limits(config_dir: Path | None = None, which: str = "agent") -> ResourceLimits:
    """Resource limits for ``which`` ('agent'|'proxy') from config.yaml ``resources``."""
    cfg = load_project_config(config_dir)
    res = cfg.get("resources")
    if not isinstance(res, dict) or which not in res:
        raise ValueError(f"Missing required 'resources.{which}' configuration in project config")
    section = res[which]
    if not isinstance(section, dict):
        raise ValueError(f"Invalid 'resources.{which}' configuration in project config: expected mapping")
    if "memory" not in section or "cpus" not in section:
        raise ValueError(f"Missing required 'memory' or 'cpus' in 'resources.{which}'")
    return {
        "memory": section["memory"],
        "cpus": section["cpus"],
    }


def resource_limit_args(limits: ResourceLimits) -> list[str]:
    """Build ``--memory``/``--cpus`` run flags, omitting falsy (null) values."""
    args: list[str] = []
    if limits.get("memory"):
        args += ["--memory", str(limits["memory"])]
    if limits.get("cpus"):
        args += ["--cpus", str(limits["cpus"])]
    return args


def read_llama_config(config_dir: Path | None = None) -> LlamaConfig:
    """llama-server startup tuning from config.yaml ``llama``."""
    section = load_project_config(config_dir).get("llama")
    if not isinstance(section, dict):
        raise ValueError("Missing required 'llama' configuration section in project config")
    if "startup_timeout" not in section or "startup_attempts" not in section:
        raise ValueError("Missing required 'startup_timeout' or 'startup_attempts' in 'llama'")
    return {
        "startup_timeout": int(section["startup_timeout"]),
        "startup_attempts": int(section["startup_attempts"]),
    }


def read_network_config(config_dir: Path | None = None) -> NetworkConfig:
    """Network settings from config.yaml ``network``."""
    section = load_project_config(config_dir).get("network")
    if not isinstance(section, dict):
        raise ValueError("Missing required 'network' configuration section in project config")
    if "ipv6" not in section or "dns" not in section:
        raise ValueError("Missing required 'ipv6' or 'dns' in 'network'")
    ipv6_val = section["ipv6"]
    if not isinstance(ipv6_val, bool):
        raise ValueError(f"Invalid 'network.ipv6': expected bool, got {type(ipv6_val).__name__}")
    return {
        "ipv6": ipv6_val,
        "dns": str(section["dns"]),
    }


def read_proxy_config(config_dir: Path | None = None) -> ProxyConfig:
    """Proxy settings from config.yaml ``proxy``."""
    section = load_project_config(config_dir).get("proxy")
    if not isinstance(section, dict):
        raise ValueError("Missing required 'proxy' configuration section in project config")
    for key in ("expose_ui", "max_view_flows", "stream_large_bodies", "open_browser"):
        if key not in section:
            raise ValueError(f"Missing required 'proxy.{key}' configuration in project config")

    expose = str(section["expose_ui"]).strip().lower()
    if expose not in ("localhost", "lan"):
        raise ValueError(f"Invalid 'proxy.expose_ui': expected 'localhost' or 'lan', got {expose!r}")

    max_flows = section["max_view_flows"]
    if max_flows is not None and (not isinstance(max_flows, int) or max_flows < 0):
        raise ValueError(f"Invalid 'proxy.max_view_flows': expected non-negative int or null, got {max_flows!r}")

    stream_bodies = section["stream_large_bodies"]
    if stream_bodies is not None:
        stream_bodies = str(stream_bodies).strip()
        if stream_bodies.lower() in ("null", "none", "off", "0", ""):
            stream_bodies = None

    open_browser = section["open_browser"]
    if not isinstance(open_browser, bool):
        raise ValueError(f"Invalid 'proxy.open_browser': expected bool, got {type(open_browser).__name__}")

    return {
        "expose_ui": expose,
        "max_view_flows": max_flows,
        "stream_large_bodies": stream_bodies,
        "open_browser": open_browser,
    }


def read_proxy_ui_expose(config_dir: Path | None = None) -> str:
    """Where the proxy's mitmweb UI is published, from config.yaml ``proxy.expose_ui``."""
    return str(read_proxy_config(config_dir)["expose_ui"])


_NESTED_STORAGE_MODES = ("volume", "tmpfs")
_NESTED_SECURITY_MODES = ("disable", "engine_t")


def _parse_port_mapping(entry: object) -> tuple[int, int]:
    """Parse one ``ports.publish`` entry to ``(host, agent)``."""
    text = str(entry).strip()
    if not text:
        raise ValueError(f"Empty port mapping entry: {entry!r}")
    host_text, sep, agent_text = text.partition(":")
    if sep:
        if not host_text.strip() or not agent_text.strip():
            raise ValueError(f"Invalid port mapping format: {entry!r} (expected 'HOST:AGENT')")
        agent_text = agent_text.strip()
    else:
        agent_text = host_text
    try:
        host, agent = int(host_text), int(agent_text)
    except ValueError as e:
        raise ValueError(f"Port mapping entry {entry!r} contains non-integer port: {e}") from e
    if not (1 <= host <= 65535 and 1 <= agent <= 65535):
        raise ValueError(f"Port numbers in entry {entry!r} out of range (must be 1..65535)")
    return host, agent


def _read_ports_section(section: Mapping[str, Any], section_name: str = "ports") -> PortPublishConfig:
    """Read a ``ports`` sub-section → ``{"expose", "publish"}``."""
    ports = section.get("ports")
    if ports is None:
        return {"expose": "localhost", "publish": []}
    if not isinstance(ports, dict):
        raise ValueError(f"'{section_name}' must be a mapping, got {type(ports).__name__}")

    expose = str(ports.get("expose") or "localhost").strip().lower()
    if expose not in ("localhost", "lan"):
        raise ValueError(f"Invalid '{section_name}.expose': expected 'localhost' or 'lan', got {expose!r}")

    raw = ports.get("publish")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError(f"'{section_name}.publish' must be a list, got {type(raw).__name__}")

    publish: list[tuple[int, int]] = []
    claimed: set[int] = set()
    for entry in raw:
        mapping = _parse_port_mapping(entry)
        if mapping[0] in claimed:
            raise ValueError(f"Duplicate host port {mapping[0]} in '{section_name}.publish'")
        claimed.add(mapping[0])
        publish.append(mapping)

    return {"expose": expose, "publish": publish}


def _read_nested_ports(section: Mapping[str, Any]) -> PortPublishConfig:
    """The ``nested_containers.ports`` sub-section → ``{"expose", "publish"}``."""
    return _read_ports_section(section, "nested_containers.ports")


def read_nested_containers_config(
    config_dir: Path | None = None,
    raw_config: dict[str, Any] | None = None,
) -> NestedContainersConfig:
    """Nested-container settings from packages list (podman) in config.yaml."""
    cfg = raw_config if raw_config is not None else load_project_config(config_dir)
    pkgs_list = cfg.get("packages")
    if pkgs_list is None:
        raise ValueError("Missing required 'packages' configuration in project config")
    podman_entry = None
    if isinstance(pkgs_list, list):
        for item in pkgs_list:
            if isinstance(item, dict) and "podman" in item:
                podman_entry = item["podman"]
                break
    if podman_entry is None:
        return {
            "enabled": False,
            "storage": "volume",
            "security": "disable",
            "ports": {"expose": "localhost", "publish": []},
        }

    podman_cfg = podman_entry.get("config") if isinstance(podman_entry, dict) else {}
    if not isinstance(podman_cfg, dict):
        raise ValueError("Invalid 'packages.podman.config': expected mapping")

    storage = str(podman_cfg.get("storage", "volume")).strip().lower()
    if storage not in _NESTED_STORAGE_MODES:
        raise ValueError(
            f"Invalid 'nested_containers.storage': expected one of {_NESTED_STORAGE_MODES}, got {storage!r}"
        )

    security = str(podman_cfg.get("security", "disable")).strip().lower()
    if security not in _NESTED_SECURITY_MODES:
        raise ValueError(
            f"Invalid 'nested_containers.security': expected one of {_NESTED_SECURITY_MODES}, got {security!r}"
        )

    if "ports" not in podman_cfg:
        raise ValueError("Missing required 'nested_containers.ports'")
    ports_cfg = _read_nested_ports(podman_cfg)

    return {
        "enabled": True,
        "storage": storage,
        "security": security,
        "ports": ports_cfg,
    }


def read_agent_extras(config_dir: Path | None = None) -> AgentExtrasConfig:
    """Extra agent-container env vars, bind mounts, capabilities, and devices from config.yaml ``agent``.

    Returns ``{"env": {NAME: value, ...}, "mounts": ["host:container[:ro]", ...], "capabilities": ["CAP_NAME", ...], "devices": ["host:container[:mode]", ...]}``
    — passed through verbatim as ``--env``/``--volume``/``--cap-add``/``--device`` flags. Use absolute host paths for mounts and devices. Empty when the section is absent.
    """
    section: ProjectAgentSectionConfig = load_project_config(config_dir).get("agent") or {}
    env = section.get("env") or {}
    mounts = section.get("mounts") or []
    capabilities = section.get("capabilities") or []
    devices = section.get("devices") or []
    return {
        "env": {str(k): str(v) for k, v in dict(env).items()},
        "mounts": [str(m) for m in mounts],
        "capabilities": [str(c) for c in capabilities],
        "devices": [str(d) for d in devices],
    }


def read_read_only_pa_container(config_dir: Path | None = None) -> bool:
    """Check whether the agent container's /workspace/.pa-container directory is read-only."""
    section = load_project_config(config_dir).get("agent")
    if not isinstance(section, dict) or "read_only_pa_container" not in section:
        raise ValueError("Missing required 'agent.read_only_pa_container' configuration")
    val = section["read_only_pa_container"]
    if not isinstance(val, bool):
        raise ValueError(f"Invalid 'agent.read_only_pa_container': expected bool, got {type(val).__name__}")
    return val


def read_agent_ports(config_dir: Path | None = None) -> PortPublishConfig:
    """Inbound host ports published directly from the agent container (config.yaml ``agent.ports``).

    Returns ``{"expose": "localhost"|"lan", "publish": [(host, agent), ...]}``.
    """
    section: ProjectAgentSectionConfig = load_project_config(config_dir).get("agent") or {}
    return _read_ports_section(section, "agent.ports")


def resolve_service_port(
    requested_port: int | str | None = None,
    default_port: int = 3773,
    host: str = "127.0.0.1",
    fallback_to_ephemeral: bool = True,
    service_name: str = "service",
) -> int:
    """Resolve an available host TCP port for a service.

    - If requested_port is provided (integer or 'auto'), it is validated.
    - If 'auto', allocates an ephemeral free port.
    - If an explicit port or default_port is free on host, returns it.
    - If busy and fallback_to_ephemeral is True, logs a warning and allocates
      a free port via get_free_port().
    - If busy and fallback_to_ephemeral is False, raises ValueError.
    """
    target_int: int | None = None
    if requested_port is not None:
        raw = str(requested_port).strip().lower()
        if raw != "auto":
            try:
                target_int = int(raw)
            except ValueError as e:
                raise ValueError(f"Invalid {service_name} port {requested_port!r}: expected integer or 'auto'") from e
            if not (1 <= target_int <= 65535):
                raise ValueError(f"{service_name} port {target_int} out of range (must be 1..65535)")
    else:
        target_int = default_port

    if target_int is None:
        return get_free_port()

    if is_port_available(target_int, host=host):
        return target_int

    if fallback_to_ephemeral:
        logger.warning(f"Configured or default {service_name} port {target_int} is in use; allocating ephemeral port.")
        return get_free_port()

    raise ValueError(f"{service_name} port {target_int} is already in use on {host}")


def read_enabled_agents(config_dir: Path | None = None) -> list[str]:
    """Read list of enabled agent names from config.yaml 'packages' list."""
    from packages.discovery import discover_packages

    cfg = load_project_config(config_dir)
    pkgs = cfg.get("packages")
    if not isinstance(pkgs, list) or not pkgs:
        raise ValueError("Missing or invalid 'packages' configuration list")

    manifests = discover_packages()
    agents: list[str] = []

    def _register_agent_pkg(pkg_name: str) -> None:
        if pkg_name == "agents":
            if "pi" not in agents:
                agents.append("pi")
        elif pkg_name.startswith("agents/"):
            ag = pkg_name.removeprefix("agents/")
            if ag not in agents:
                agents.append(ag)
        elif pkg_name in manifests and manifests[pkg_name].category == "agents" and pkg_name not in agents:
            agents.append(pkg_name)

    for entry in pkgs:
        if isinstance(entry, str):
            _register_agent_pkg(entry.strip().lower())
        elif isinstance(entry, dict):
            for k in entry:
                _register_agent_pkg(str(k).strip().lower())

    if not agents:
        raise ValueError(
            "No agent package configured in 'packages'. At least one package of category 'agents' is required."
        )
    return agents


def read_default_agent(config_dir: Path | None = None) -> str:
    """Agent engine type from 'agent.default' or first configured agent package in config.yaml 'packages'."""
    cfg = load_project_config(config_dir)
    agent_sec = cfg.get("agent")
    if isinstance(agent_sec, dict) and agent_sec.get("default"):
        return str(agent_sec["default"]).strip().lower()
    enabled = read_enabled_agents(config_dir)
    return enabled[0]


def read_logging_config(config_dir: Path | None = None) -> LoggingProjectConfig:
    """Read the logging section from .pa-container/config.yaml."""
    sec = load_project_config(config_dir).get("logging")
    if not isinstance(sec, dict):
        return {}
    ret = sec.get("retention")
    ret_dict: LogRetentionConfig = {}
    if isinstance(ret, dict):
        max_d = ret.get("max_days")
        max_l = ret.get("max_launches")
        ret_dict = {
            "max_days": int(max_d) if max_d is not None else None,
            "max_launches": int(max_l) if max_l is not None else None,
        }
    return {
        "log_level": str(sec["log_level"]) if sec.get("log_level") is not None else None,
        "retention": ret_dict,
    }


# ─── Token Replacer Config Scanner (duplicated from coding-agent-proxy/addons/token_replacer)
#
# run.py lives outside coding-agent-proxy and must not import from it.
# This function is duplicated here so run.py can scan the host-side token
# replacer config for ${ENV:VAR} references and pull required secrets from
# the host environment / secret store before launching the container.
#
# Source of truth: addons/token_replacer/token_replacer.py
# ──────────────────────────────────────────────────────────────────────────

_TOKEN_REPLACER_ENV_VAR_REQUIRED_PATTERN = re.compile(r"^\$\{ENV:([^,}]+)\}$")


def scan_config_env_refs(config: dict[str, Any]) -> list[str]:
    """Scan a parsed config dict for required env-var references.

    Finds all ``${ENV:VAR}`` references (no default value) in
    ``replace_with.value`` fields across every rule. These are the values
    the host must pull from a secret store before launching the container.

    Args:
        config: The parsed YAML config dict (as returned by ``load_yaml_file``).

    Returns:
        A deduplicated, sorted list of env var names that are required.
    """
    refs: set[str] = set()
    rules = config.get("rules") or []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        replace = rule.get("replace_with") or {}
        if not isinstance(replace, dict):
            continue
        value = replace.get("value", "")
        m = _TOKEN_REPLACER_ENV_VAR_REQUIRED_PATTERN.match(str(value))
        if m:
            refs.add(m.group(1))
    return sorted(refs)


# ─── Container Network Manager ───────────────────────────────────────────


class ContainerNetworkManager:
    def __init__(
        self,
        container_runtime: str | PodmanRuntime,
        network_name: str,
        proxy_image: str,
        proxy_name: str = "proxy",
        config_dir: Path | None = None,
        llama_ports: str | None = None,
        llama_hostnames: str | None = None,
        ipv6: bool = False,
        lock_dir: Path | None = None,
        project_dir: Path | None = None,
        gateway_configs: list[GatewayConfigItem] | None = None,
    ) -> None:
        # Accept either a runtime name or a ready PodmanRuntime.
        self.runtime: PodmanRuntime = (
            container_runtime if isinstance(container_runtime, PodmanRuntime) else PodmanRuntime()
        )
        self.container_runtime: str = self.runtime.name
        self.network_name: str = network_name
        self.proxy_image: str = proxy_image
        self.proxy_name: str = proxy_name
        self.config_dir: Path = config_dir or (PROJECT_DIR / ".pa-container")
        self.project_dir: Path = (
            project_dir or (self.config_dir.parent if self.config_dir.name == ".pa-container" else self.config_dir)
        ).resolve()
        self.project_hash: str = self.proxy_name.removeprefix("pa-container-proxy-")
        self.llama_ports: str | None = llama_ports
        self.llama_hostnames: str | None = llama_hostnames
        self.ipv6: bool = ipv6
        self.gateway_configs: list[GatewayConfigItem] = gateway_configs or []
        # Host port the proxy's mitmweb UI is published on. Auto-assigned when
        # this process starts the proxy; resolved from the running container when
        # attaching to an already-running one. See ``mitmweb_url``.
        self.mitmweb_port: int | None = None

        # Directory for cross-process synchronization. Kept under user cache (not a
        # user workspace) so lock files never pollute projects. The proxy is
        # per-project, so refcount files are keyed by proxy_name — each workspace
        # refcounts (and tears down) its own proxy independently.
        self.lock_dir: Path = lock_dir if lock_dir is not None else PROXY_LOCK_DIR
        self.paths: dict[str, Path] = {
            "lock_dir": self.lock_dir,
            "ref_count_lock": self.lock_dir / f".{self.proxy_name}.lock",
            "clients_file": self.lock_dir / f".{self.proxy_name}.clients.json",
        }

    def _synthesize_proxy_configs(self) -> tuple[Path, Path]:
        """Synthesize effective proxy allowlist.yaml and token_replacer.yaml in runtime cache."""
        import copy

        import yaml

        from yaml_strict import load_yaml_file

        runtime_dir = self.lock_dir / f"proxy-{self.project_hash}"
        runtime_dir.mkdir(parents=True, exist_ok=True)

        # 1. Effective allowlist
        allowlist_path = self.config_dir / "allowlist.yaml"
        effective_allowlist: dict[str, Any]
        if allowlist_path.is_file():
            try:
                loaded = load_yaml_file(allowlist_path)
                effective_allowlist = copy.deepcopy(loaded) if isinstance(loaded, dict) else {}
            except Exception as e:
                logger.warning(f"Could not load {allowlist_path}: {e}")
                effective_allowlist = {}
        else:
            effective_allowlist = {}

        if "global" not in effective_allowlist or not isinstance(effective_allowlist["global"], dict):
            effective_allowlist["global"] = {
                "mode": "allow",
                "default_action": "block",
                "status_code": 403,
                "rules": [],
            }
        else:
            if "rules" not in effective_allowlist["global"] or not isinstance(
                effective_allowlist["global"]["rules"], list
            ):
                effective_allowlist["global"]["rules"] = []

        for gw in self.gateway_configs:
            gw_def = gw.get("gatewayDef")
            if gw_def and gw_def.allowlist:
                for rule in gw_def.allowlist:
                    r_copy = copy.deepcopy(rule)
                    if gw.get("name") and gw["name"] != gw_def.id:
                        r_copy["name"] = f"{r_copy.get('name', 'Gateway Allowlist')} ({gw['name']})"
                    effective_allowlist["global"]["rules"].append(r_copy)

        active_feats: dict[str, list[str]] = {}
        if self.project_dir:
            try:
                from images import resolve_project_packages

                active_feats = resolve_project_packages(self.project_dir, include_core=True)
            except Exception as e:
                logger.debug(f"Could not resolve project packages: {e}")
        else:
            try:
                from packages import get_core_packages

                active_feats = {p: [] for p in get_core_packages()}
            except Exception as e:
                logger.debug(f"Could not get core packages: {e}")

        try:
            from packages import aggregate_egress_hosts, discover_packages

            all_manifests = discover_packages()
            active_manifests = [all_manifests[p] for p in active_feats if p in all_manifests]

            pkg_hosts = aggregate_egress_hosts(active_manifests, active_features=active_feats)
            if pkg_hosts:
                effective_allowlist["global"]["rules"].append(
                    {
                        "name": "Package Egress Allowlist",
                        "mode": "allow",
                        "hosts": pkg_hosts,
                    }
                )
        except Exception as e:
            logger.debug(f"Could not aggregate package egress allowlist: {e}")

        effective_allowlist_file = runtime_dir / "allowlist.yaml"
        effective_allowlist_file.write_text(yaml.safe_dump(effective_allowlist, sort_keys=False))

        # 2. Effective token replacer
        replacer_path = self.config_dir / "token_replacer.yaml"
        effective_replacer: dict[str, Any]
        if replacer_path.is_file():
            try:
                loaded = load_yaml_file(replacer_path)
                effective_replacer = copy.deepcopy(loaded) if isinstance(loaded, dict) else {}
            except Exception as e:
                logger.warning(f"Could not load {replacer_path}: {e}")
                effective_replacer = {}
        else:
            effective_replacer = {}

        if "global" not in effective_replacer or not isinstance(effective_replacer["global"], dict):
            effective_replacer["global"] = {
                "log_replacements": True,
                "dry_run": False,
            }
        if "rules" not in effective_replacer or not isinstance(effective_replacer["rules"], list):
            effective_replacer["rules"] = []

        for gw in self.gateway_configs:
            gw_def = gw.get("gatewayDef")
            if gw_def and gw_def.token_replacer:
                provider_name = gw.get("name") or gw_def.id
                model_id = gw_def.id
                container_env_var = gw.get("containerEnvVar", "")
                base_placeholder = f"{model_id.upper().replace('-', '_')}_API_KEY_PLACEHOLDER"
                inst_placeholder = f"{provider_name.upper().replace('-', '_')}_API_KEY_PLACEHOLDER"

                for rule in gw_def.token_replacer:
                    r_copy = copy.deepcopy(rule)
                    if provider_name != model_id:
                        r_copy["name"] = f"{r_copy.get('name', 'Token Replacer Rule')} ({provider_name})"
                    if container_env_var:
                        rw = r_copy.get("replace_with")
                        if isinstance(rw, dict) and rw.get("value"):
                            rw["value"] = rw["value"].replace("${ENV:containerEnvVar}", f"${{ENV:{container_env_var}}}")
                    for pat in r_copy.get("content_patterns", []):
                        if isinstance(pat, dict) and pat.get("regex"):
                            pat["regex"] = pat["regex"].replace(base_placeholder, inst_placeholder)
                    effective_replacer["rules"].append(r_copy)

        try:
            from packages import aggregate_token_replacers, discover_packages

            all_manifests = discover_packages()
            active_manifests = [all_manifests[p] for p in active_feats if p in all_manifests]

            pkg_tokens = aggregate_token_replacers(active_manifests, active_features=active_feats)
            for pt in pkg_tokens:
                rule_entry: dict[str, Any] = {
                    "name": pt["name"],
                    "hostnames": list(pt.get("hostnames") or ["*"]),
                    "content_patterns": [dict(cp) for cp in pt.get("content_patterns") or []],
                    "replace_with": dict(pt.get("replace_with") or {"strategy": "static", "value": "REDACTED"}),
                }
                effective_replacer["rules"].append(rule_entry)
        except Exception as e:
            logger.debug(f"Could not aggregate package token replacers: {e}")

        effective_replacer_file = runtime_dir / "token_replacer.yaml"
        effective_replacer_file.write_text(yaml.safe_dump(effective_replacer, sort_keys=False))

        return effective_allowlist_file, effective_replacer_file

    def _pull_secrets_from_config(self) -> dict[str, str]:
        """Pull secrets required by the mounted token_replacer config.

        Scans the config file for ``${ENV:VAR}`` references (no default value)
        in ``replace_with.value`` fields, then resolves each one from the
        trusted host-side secret sources. Returns a dict of var_name -> value
        for non-empty values.

        Resolution order:
        1. The in-process registry of secrets resolved by trusted host-side
           components (ACP plugins). This is authoritative — it reflects the
           keyring account the user explicitly declared in config.yaml.
        2. The OS keyring (service ``pa-container``, account = variable name).

        Override this method to integrate with an external secret store
        (Vault, AWS Secrets Manager, Azure Key Vault, etc.).
        """
        _, effective_replacer_path = self._synthesize_proxy_configs()
        if not effective_replacer_path.exists():
            logger.warning(
                f"Token replacer config not found at {effective_replacer_path}; "
                f"no secrets will be injected into the proxy container."
            )
            return {}

        from secret_store import get_keyring_secret, get_resolved_secret
        from yaml_strict import load_yaml_file

        loaded = load_yaml_file(effective_replacer_path)
        config = loaded if isinstance(loaded, dict) else {}

        required_vars = scan_config_env_refs(config)
        if not required_vars:
            logger.info("No required env-var secrets found in token replacer config.")
            return {}

        secrets: dict[str, str] = {}
        for var in required_vars:
            value = get_resolved_secret(var) or get_keyring_secret(var)
            if value:
                secrets[var] = value
                os.environ[var] = value
            else:
                logger.warning(
                    f"Required secret '{var}' (referenced by token replacer config) "
                    f"was not found in the OS keyring or resolved host-side secrets. "
                    f"The container will use the config's fallback default, if any. "
                    f"To store in keyring: uv run keyring set pa-container {var}"
                )
        return secrets

    def _env_flags(self, secrets: dict[str, str]) -> list[str]:
        """Convert a secrets dict into ``--env KEY`` flag pairs.

        Emits ``--env KEY`` without ``=VALUE`` so secret values are not exposed in
        CLI process listings (ps aux / argv). The actual values are supplied via the
        parent process environment dict.
        """
        flags: list[str] = []
        for k in sorted(secrets.keys()):
            flags.extend(["--env", k])
        return flags

    def _preflight_ipv6_egress(self) -> None:
        """Warn if IPv6 was requested but the runtime likely can't egress it.

        Layered, cheapest first:
          1. Static per-runtime capability (``ipv6_upstream_egress``) — short-
             circuit for runtimes known to NAT IPv4 only.
          2. Inspect the upstream network's config for IPv6 enablement.
        The definitive check against the proxy's real ``eth0`` happens after the
        proxy starts (in run.py).
        """
        # (1) Static: runtime known to lack IPv6 egress entirely.
        if not self.runtime.ipv6_upstream_egress:
            logger.warning(
                f"network.ipv6=true but runtime '{self.container_runtime}' provides no "
                f"IPv6 egress on the upstream network (it NATs IPv4 only); the proxy will "
                f"have no IPv6 route out, so agent IPv6 connections will fail. Set "
                f"network.ipv6=false in .pa-container/config.yaml unless you are on a "
                f"runtime/host with working IPv6 egress."
            )
            return

        # (2) Inspect the upstream network config.
        has_v6 = self.runtime.upstream_network_has_ipv6()
        if has_v6 is False:
            logger.warning(
                f"network.ipv6=true but the upstream network '{self.runtime.upstream_network}' "
                f"is not configured for IPv6; the proxy will likely have no IPv6 route out and "
                f"agent IPv6 connections may fail."
            )
        elif has_v6 is None:
            logger.info(
                f"Could not determine IPv6 config of upstream network "
                f"'{self.runtime.upstream_network}'; proceeding (egress is re-checked on the "
                f"running proxy)."
            )

    def warn_if_proxy_lacks_ipv6_egress(self, upstream_iface: str = "eth0") -> None:
        """Confirm the *running* proxy actually has IPv6 egress on its upstream NIC.

        This is the definitive, observed check: static capability and
        upstream-network config are checked preflight in :meth:`_preflight_ipv6_egress`,
        but only the live proxy tells us whether ``eth0`` got a global v6 address AND a
        v6 default route. Warns (does not fail) when either is missing, since IPv4
        still works and the agent's own IPv6 is disabled unless a route was found.
        """
        try:
            addr = subprocess.run(
                [self.container_runtime, "exec", self.proxy_name, "ip", "-6", "addr", "show", upstream_iface],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
            route = subprocess.run(
                [self.container_runtime, "exec", self.proxy_name, "ip", "-6", "route", "show", "default"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        except Exception as e:
            logger.warning(f"Could not verify proxy IPv6 egress: {e}")
            return

        has_global = bool(re.search(r"inet6\s+[0-9a-fA-F:]+/\d+\s+scope global", addr))
        has_default = bool(route.strip())
        if not (has_global and has_default):
            logger.warning(
                f"network.ipv6=true but the proxy has no working IPv6 egress on {upstream_iface} "
                f"(global address: {has_global}, default route: {has_default}); this runtime/host "
                f"does not route IPv6 to the internet, so agent IPv6 connections will fail. "
                f"Set network.ipv6=false in .pa-container/config.yaml to silence this."
            )
        else:
            logger.info(f"Proxy has IPv6 egress on {upstream_iface} (global address + default route present).")

    def __enter__(self) -> ContainerNetworkManager:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        self.stop()

    def start(self) -> None:
        self.paths["lock_dir"].mkdir(exist_ok=True, parents=True)

        client_info: ClientInfo = {
            "pid": os.getpid(),
            "proxy_name": self.proxy_name,
            "registered_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        start_refcounted_resource(
            lock_file=self.paths["ref_count_lock"],
            clients_file=self.paths["clients_file"],
            client_info=client_info,
            is_healthy_fn=self._is_existing_proxy_healthy,
            start_fn=self._actually_start,
            stop_fn=self._actually_stop,
            cleanup_stale_fn=self._cleanup_stale_refcount,
            on_adopt_fn=lambda: logger.info(f"Adopting existing healthy proxy {self.proxy_name}"),
            logger=logger,
            label=f"proxy {self.proxy_name}",
        )

    def stop(self) -> None:
        def _cleanup_lock_dir() -> None:
            with contextlib.suppress(OSError):
                if self.paths["lock_dir"].exists() and not any(self.paths["lock_dir"].iterdir()):
                    self.paths["lock_dir"].rmdir()

        stop_refcounted_resource(
            lock_file=self.paths["ref_count_lock"],
            clients_file=self.paths["clients_file"],
            pid=os.getpid(),
            stop_fn=self._actually_stop,
            full_cleanup_fn=_cleanup_lock_dir,
            logger=logger,
            label=f"proxy {self.proxy_name}",
        )

    @classmethod
    def cleanup_orphaned_proxies(cls, runtime: str | PodmanRuntime, lock_dir: Path) -> list[str]:
        """Scan lock_dir for proxy instances whose clients are all dead, and stop them."""
        if not lock_dir.exists():
            return []

        runtime_bin = getattr(runtime, "runtime", str(runtime))
        cleaned: list[str] = []
        seen_proxies: set[str] = set()

        for entry in lock_dir.iterdir():
            name = entry.name
            if not name.startswith("."):
                continue
            parts = name[1:].split(".")
            if parts and parts[0].startswith("pa-container-proxy-"):
                seen_proxies.add(parts[0])

        for proxy_name in sorted(seen_proxies):
            lock_file = lock_dir / f".{proxy_name}.lock"
            clients_file = lock_dir / f".{proxy_name}.clients.json"

            if not lock_file.exists() and not clients_file.exists():
                continue

            try:
                with lock_file.open("a") as lf:
                    try:
                        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError, OSError:
                        continue

                    live_clients = read_live_clients(clients_file)
                    if not live_clients:
                        if clients_file.exists():
                            logger.info(f"Stopping orphaned proxy container {proxy_name}...")
                            run_quiet(
                                [runtime_bin, "rm", "-f", proxy_name],
                                check=False,
                                label=f"remove orphaned proxy container {proxy_name}",
                                logger=logger,
                            )
                            project_hash = proxy_name.removeprefix("pa-container-proxy-")
                            network_name = f"pa-container-isolated-net-{project_hash}"
                            logger.info(f"Removing orphaned proxy network {network_name}...")
                            run_quiet(
                                [runtime_bin, "network", "rm", network_name],
                                check=False,
                                label=f"remove orphaned proxy network {network_name}",
                                logger=logger,
                            )
                            clients_file.unlink(missing_ok=True)
                            cleaned.append(proxy_name)
                        lock_file.unlink(missing_ok=True)
            except Exception as e:
                logger.debug(f"Could not check/clean proxy lock {lock_file}: {e}")

        with contextlib.suppress(OSError):
            if lock_dir.exists() and not any(lock_dir.iterdir()):
                lock_dir.rmdir()

        return cleaned

    def _get_ref_count(self) -> int:
        return get_ref_count(self.paths["clients_file"])

    def _actually_start(self) -> None:
        from secret_store import get_keyring_secret

        self._admin_password = get_keyring_secret("ADMIN_PASSWORD") or ""
        # Pull secrets required by the mounted token_replacer config
        secrets = self._pull_secrets_from_config()
        proxy_cfg = read_proxy_config(self.config_dir)

        # IPv6 can be plumbed on the isolated side, but it only works end-to-end
        # if the runtime also provides IPv6 egress on the upstream network.
        # Preflight this so we warn rather than fail confusingly later.
        if self.ipv6:
            self._preflight_ipv6_egress()

        # Create the isolated internal network (skip if it already exists).
        logger.info(f"Checking network {self.network_name}...")
        result = subprocess.run(
            [self.container_runtime, "network", "inspect", self.network_name], capture_output=True, text=True
        )
        if result.returncode != 0:
            logger.info(f"Creating network {self.network_name} (ipv6={self.ipv6})...")
            run_quiet(
                [self.container_runtime, *self.runtime.create_isolated_network_argv(self.network_name, ipv6=self.ipv6)],
                label=f"create network {self.network_name}",
                logger=logger,
            )
        else:
            logger.info(f"Network {self.network_name} already exists, skipping creation.")

        # Start proxy container. It attaches to both networks at run time — the
        # upstream network (eth0 → internet) and the isolated network (eth1 →
        # agent), with interface names pinned. LLAMA_HOST_ADDR
        # tells the proxy where to DNAT llama-server traffic; when unset the
        # proxy falls back to resolving its own default gateway.
        logger.info(f"Starting proxy container {self.proxy_name} from {self.proxy_image}...")
        llama_host_addr = self.runtime.resolve_llama_host_addr(self.proxy_image)

        # Publish the mitmweb UI on an auto-assigned host port so multiple
        # per-project proxies can coexist (the old fixed 8081 could bind once).
        self.mitmweb_port = get_free_port()

        # Mount the synthesized effective addon configs (combining workspace config
        # and enabled gateway definitions) over the image's baked defaults.
        effective_allowlist, effective_replacer = self._synthesize_proxy_configs()
        config_mounts: list[str] = [
            "--volume",
            f"{effective_replacer}:/home/mitmproxy/config/token_replacer.yaml:ro",
            "--volume",
            f"{effective_allowlist}:/home/mitmproxy/config/allowlist.yaml:ro",
        ]

        # Mount a host directory for flow exports. The flow_export addon appends
        # each flow to a per-client-IP JSON Lines file (flows-<ip>.jsonl) under
        # /home/mitmproxy/exports inside the container; this mount makes them
        # accessible to run.py on the host after the session. The host directory
        # must exist first: podman refuses to auto-create a bind-mount source and
        # the container would fail to start (surfacing as a 30s health-probe
        # hang, since the run error → DEVNULL).
        exports_host_dir = self.config_dir / "exports"
        exports_container_path = "/home/mitmproxy/exports"
        # Only mount the exports volume and enable the addon when the user has
        # opted in (flow_export.enabled = true). When disabled, the addon stays
        # silent (see FLOW_EXPORT_ENABLED below) so no raw flows-<ip>.jsonl files
        # pollute the host-side exports directory.
        flow_export_enabled = read_flow_export_enabled(self.config_dir)
        exports_mounts: list[str]
        if flow_export_enabled:
            exports_host_dir.mkdir(parents=True, exist_ok=True)
            exports_mounts = [
                "--volume",
                f"{exports_host_dir}:{exports_container_path}",
            ]
        else:
            exports_mounts = []

        from security import read_security_config

        security_cfg = read_security_config(self.config_dir)

        cmd = [
            self.container_runtime,
            "run",
            "-d",
            "--rm",
            "--name",
            self.proxy_name,
            "--label",
            "pa-container.type=proxy",
            "--label",
            f"pa-container.project.hash={self.project_hash}",
            "--label",
            f"pa-container.project.path={str(self.project_dir)}",
            "--label",
            f"pa-container.project.name={self.project_dir.name}",
            "--security-opt",
            "no-new-privileges",
            *self.runtime.proxy_network_args(self.network_name),
            *self.runtime.proxy_extra_run_args(),
            "--cap-add",
            "NET_ADMIN",
            # Upstream resolver for the proxy (config.yaml network.dns).
            "--dns",
            read_network_config(self.config_dir)["dns"],
            # Resource limits for this project's proxy (config.yaml resources.proxy).
            *resource_limit_args(read_resource_limits(self.config_dir, "proxy")),
            # Publish the mitmweb UI on the auto-assigned port; bind scope from
            # config.yaml proxy.expose_ui (localhost by default, or lan → 0.0.0.0).
            *self._mitmweb_publish_args(),
            # IPv6 policy: --sysctl toggle (VM runtimes) + env flag the proxy
            # entrypoint reads to mirror (or tear down) v6 firewall rules.
            *self.runtime.ipv6_run_args(self.ipv6, forwarding=True),
            "--env",
            f"IPV6_ENABLED={str(self.ipv6).lower()}",
            "--env",
            f"ADMIN_PASSWORD={self._admin_password}",
            *(["--env", f"LLAMA_PORTS={self.llama_ports}"] if self.llama_ports else []),
            *(["--env", f"LLAMA_HOSTNAMES={self.llama_hostnames}"] if self.llama_hostnames else []),
            *(["--env", f"LLAMA_HOST_ADDR={llama_host_addr}"] if llama_host_addr else []),
            *(
                ["--env", f"PROXY_BLOCKED_IP_RANGES={json.dumps(security_cfg['blocked_ip_ranges'])}"]
                if security_cfg.get("blocked_ip_ranges")
                else []
            ),
            # Per-protocol forwarding opt-ins (uninspected protocols), read from
            # this project's config.yaml (egress.allow).
            *[flag for k, v in read_proxy_forward_env(self.config_dir).items() for flag in ("--env", f"{k}={v}")],
            *config_mounts,
            *exports_mounts,
            # Flow export toggle — forwarded to the proxy addon so it skips
            # capture entirely when the user has disabled it in config.yaml.
            "--env",
            f"FLOW_EXPORT_ENABLED={str(flow_export_enabled).lower()}",
            *(
                ["--env", f"PROXY_MAX_VIEW_FLOWS={proxy_cfg['max_view_flows']}"]
                if proxy_cfg["max_view_flows"] is not None
                else []
            ),
            *(
                ["--env", f"PROXY_STREAM_LARGE_BODIES={proxy_cfg['stream_large_bodies']}"]
                if proxy_cfg["stream_large_bodies"] is not None
                else []
            ),
            *self._env_flags(secrets),
            self.proxy_image,
        ]
        # Label (not the argv) is what surfaces on failure — cmd carries
        # ADMIN_PASSWORD and must never reach logs/tracebacks.
        proxy_env = os.environ.copy()
        if secrets:
            proxy_env.update(secrets)
        run_quiet(cmd, env=proxy_env, label=f"start proxy container {self.proxy_name}", logger=logger)

        # Wait for proxy to be ready via health probe
        self._wait_for_proxy_health(timeout=30)

    def _actually_stop(self) -> None:
        logger.info(f"Removing proxy container {self.proxy_name}...")
        # Teardown is best-effort: a container/network that is already gone must
        # not abort cleanup, so check=False (log a warning, don't raise).
        # ``rm -f`` handles both running and exited containers in one step —
        # running containers are killed, exited ones are removed. Using rm
        # instead of stop+rm avoids the two-step gap where an exited container
        # still occupies the name and blocks a subsequent ``run --name``.
        run_quiet(
            [self.container_runtime, "rm", "-f", self.proxy_name],
            check=False,
            label=f"remove proxy container {self.proxy_name}",
            logger=logger,
        )

        delete_argv = self.runtime.delete_isolated_network_argv(self.network_name)
        if delete_argv:
            logger.info(f"Removing network {self.network_name}...")
            run_quiet(
                [self.container_runtime, *delete_argv],
                check=False,
                label=f"remove network {self.network_name}",
                logger=logger,
            )

    def _is_existing_proxy_healthy(self) -> bool:
        """Check whether the already-running proxy container is alive, responsive,
        and configured for this run's port forwarding.

        Checks:
          1. ``podman port`` resolves the published mitmweb port.
          2. An HTTP request to mitmweb returns 2xx/3xx/4xx.
          3. The running container's LLAMA_PORTS and LLAMA_HOSTNAMES match this run.
             If llama-server was restarted on new host ports, the existing proxy
             holds stale DNAT rules and must be restarted.
        """
        port = self._query_published_port()
        if port is None:
            return False
        url = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(url, timeout=3):
                pass
        except urllib.error.HTTPError as e:
            # 4xx means the server is alive and responding (e.g. mitmweb
            # returns 401 for unauthenticated endpoints). 5xx means the
            # server is up but broken — treat as unhealthy.
            if not (400 <= e.code < 500):
                return False
        except Exception as e:
            logger.debug(f"Proxy health check URL probe failed ({url}): {e}")
            return False

        # Verify that the running proxy's LLAMA_PORTS and LLAMA_HOSTNAMES match
        try:
            inspect_res = subprocess.run(
                [self.container_runtime, "inspect", self.proxy_name, "--format", "{{json .Config.Env}}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if inspect_res.returncode != 0:
                return False
            import json as _json

            env_list = _json.loads(inspect_res.stdout.strip())
            env_dict = {}
            for item in env_list:
                if "=" in item:
                    k, v = item.split("=", 1)
                    env_dict[k] = v

            running_ports = env_dict.get("LLAMA_PORTS")
            expected_ports = self.llama_ports
            if (running_ports or None) != (expected_ports or None):
                logger.info(
                    f"Running proxy {self.proxy_name} has stale LLAMA_PORTS "
                    f"({running_ports!r} != {expected_ports!r}); restarting proxy."
                )
                return False

            running_hosts = env_dict.get("LLAMA_HOSTNAMES")
            expected_hosts = self.llama_hostnames
            if (running_hosts or None) != (expected_hosts or None):
                logger.info(
                    f"Running proxy {self.proxy_name} has stale LLAMA_HOSTNAMES "
                    f"({running_hosts!r} != {expected_hosts!r}); restarting proxy."
                )
                return False

            # Verify that running proxy secrets match expected secrets from config
            expected_secrets = self._pull_secrets_from_config()
            for sec_name, sec_val in expected_secrets.items():
                if env_dict.get(sec_name) != sec_val:
                    logger.info(f"Running proxy {self.proxy_name} has stale secret {sec_name}; restarting proxy.")
                    return False

        except Exception as e:
            logger.debug(f"Could not inspect running proxy env: {e}")
            return False

        return True

    def _cleanup_stale_refcount(self) -> None:
        """Remove stale client artifacts so the next start() begins fresh."""
        self.paths["clients_file"].unlink(missing_ok=True)

    def _wait_for_proxy_health(self, timeout: int = 30) -> None:
        """Wait for the proxy container's mitmweb UI to become healthy.

        Polls the mitmweb HTTP endpoint every 2 seconds until a response is
        received (any status code means the container is alive and responding).

        Raises:
            RuntimeError: If the proxy does not become healthy within timeout.
        """
        url = f"http://127.0.0.1:{self.mitmweb_port}"
        elapsed = 0
        while elapsed < timeout:
            try:
                urllib.request.urlopen(url, timeout=2)
                logger.info(f"Proxy container is healthy ({elapsed}s)")
                return
            except urllib.error.HTTPError as e:
                # HTTP error means the server is alive, just returning a status code
                if 400 <= e.code < 500:
                    logger.info(f"Proxy container is healthy (HTTP {e.code})")
                    return
            except Exception as e:
                logger.debug(f"Proxy health polling iteration failed: {e}")
            time.sleep(2)
            elapsed += 2

        raise RuntimeError(
            f"Proxy container did not become healthy within {timeout}s. "
            f"Check proxy logs: {self.container_runtime} logs {self.proxy_name}"
        )

    def _mitmweb_publish_args(self) -> list[str]:
        """Generate `-p` flags publishing the mitmweb web interface on the host."""
        host = "127.0.0.1:" if read_proxy_ui_expose(self.config_dir) == "localhost" else ""
        return ["-p", f"{host}{self.mitmweb_port}:8081"]

    def mitmweb_url(self) -> str | None:
        """Return the published host URL for this project's mitmweb web interface."""
        if self.mitmweb_port is None:
            self.mitmweb_port = self._query_published_port()
        return f"http://127.0.0.1:{self.mitmweb_port}" if self.mitmweb_port else None

    def _query_published_port(self) -> int | None:
        """Query the container runtime for the host port mapped to proxy port 8081."""
        return query_container_port(self.container_runtime, self.proxy_name, 8081)


def query_container_port(runtime_bin: str, container_name: str, target_port: int = 8081) -> int | None:
    """Query the container runtime for the host port mapped to a container port."""
    try:
        out = subprocess.run(
            [runtime_bin, "port", container_name, f"{target_port}/tcp"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            match = re.search(r":(\d+)\s*$", out.stdout.strip().splitlines()[0])
            return int(match.group(1)) if match else None
    except Exception as e:
        logger.debug(f"Failed to query container port for {container_name}:{target_port}: {e}")
    return None


def check_proxy_health(url: str, timeout: float = 1.0) -> bool:
    """Check if the mitmweb URL responds to an HTTP request."""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except urllib.error.HTTPError as e:
        return 200 <= e.code < 500
    except Exception as e:
        logger.debug(f"Proxy URL health check failed ({url}): {e}")
        return False


@dataclass
class ActiveProxyInfo:
    """Status and connection details for an active mitmweb proxy container."""

    project_name: str
    project_path: Path | None
    project_hash: str
    container_name: str
    mitmweb_port: int | None
    mitmweb_url: str | None
    is_healthy: bool
    active_clients: int
    created_at: str | None = None


def get_project_proxy(
    project_dir: Path,
    runtime: str | PodmanRuntime | None = None,
    lock_dir: Path | None = None,
) -> ActiveProxyInfo | None:
    """Return active proxy info for a specific project directory, or None if not running."""
    runtime_bin = getattr(runtime, "runtime", str(runtime)) if runtime else "podman"
    actual_lock_dir = lock_dir if lock_dir is not None else PROXY_LOCK_DIR

    from project import project_key

    proj_hash = project_key(project_dir)
    container_name = f"pa-container-proxy-{proj_hash}"

    # Verify if container is running
    try:
        proc = subprocess.run(
            [runtime_bin, "inspect", container_name, "--format", "{{.State.Running}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0 or proc.stdout.strip().lower() != "true":
            return None
    except Exception as e:
        logger.debug(f"Failed to inspect running state for proxy {container_name}: {e}")
        return None

    port = query_container_port(runtime_bin, container_name, 8081)
    url = f"http://127.0.0.1:{port}" if port else None
    clients_file = actual_lock_dir / f".{container_name}.clients.json"
    active_clients = len(read_live_clients(clients_file)) if clients_file.exists() else 0
    is_healthy = check_proxy_health(url) if url else False

    return ActiveProxyInfo(
        project_name=project_dir.resolve().name,
        project_path=project_dir.resolve(),
        project_hash=proj_hash,
        container_name=container_name,
        mitmweb_port=port,
        mitmweb_url=url,
        is_healthy=is_healthy,
        active_clients=active_clients,
    )


def list_active_proxies(
    runtime: str | PodmanRuntime | None = None,
    lock_dir: Path | None = None,
) -> list[ActiveProxyInfo]:
    """Discover all active proxy containers across the host."""
    runtime_bin = getattr(runtime, "runtime", str(runtime)) if runtime else "podman"
    actual_lock_dir = lock_dir if lock_dir is not None else PROXY_LOCK_DIR

    proxies: list[ActiveProxyInfo] = []
    seen_containers: set[str] = set()

    # 1. Query running containers matching name=pa-container-proxy-
    try:
        proc = subprocess.run(
            [runtime_bin, "ps", "--filter", "name=pa-container-proxy-", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                raw_data = json.loads(proc.stdout)
                containers = raw_data if isinstance(raw_data, list) else [raw_data]
            except json.JSONDecodeError:
                containers = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]

            for c in containers:
                names = c.get("Names") or []
                if isinstance(names, str):
                    names = [names]
                if not names:
                    continue
                name = names[0].lstrip("/")
                if not name.startswith("pa-container-proxy-"):
                    continue
                seen_containers.add(name)

                labels = c.get("Labels") or {}
                if not isinstance(labels, dict):
                    labels = {}

                proj_hash = labels.get("pa-container.project.hash") or name.removeprefix("pa-container-proxy-")
                proj_name = labels.get("pa-container.project.name") or proj_hash
                proj_path_raw = labels.get("pa-container.project.path")
                proj_path = Path(proj_path_raw) if proj_path_raw else None

                port = query_container_port(runtime_bin, name, 8081)
                url = f"http://127.0.0.1:{port}" if port else None

                clients_file = actual_lock_dir / f".{name}.clients.json"
                active_clients = len(read_live_clients(clients_file)) if clients_file.exists() else 0

                is_healthy = check_proxy_health(url) if url else False
                created_at = c.get("Created") or c.get("CreatedAt")

                proxies.append(
                    ActiveProxyInfo(
                        project_name=proj_name,
                        project_path=proj_path,
                        project_hash=proj_hash,
                        container_name=name,
                        mitmweb_port=port,
                        mitmweb_url=url,
                        is_healthy=is_healthy,
                        active_clients=active_clients,
                        created_at=str(created_at) if created_at else None,
                    )
                )
    except Exception as e:
        logger.debug(f"Error listing active proxies via {runtime_bin}: {e}")

    # 2. Fallback to lock files for any proxy container not caught above
    if actual_lock_dir.exists():
        for entry in actual_lock_dir.iterdir():
            if entry.name.startswith(".pa-container-proxy-") and entry.name.endswith(".clients.json"):
                name = entry.name[1:].removesuffix(".clients.json")
                if name in seen_containers:
                    continue
                port = query_container_port(runtime_bin, name, 8081)
                if port is None:
                    continue
                seen_containers.add(name)
                proj_hash = name.removeprefix("pa-container-proxy-")
                clients = len(read_live_clients(entry))
                url = f"http://127.0.0.1:{port}"
                is_healthy = check_proxy_health(url)
                proxies.append(
                    ActiveProxyInfo(
                        project_name=proj_hash,
                        project_path=None,
                        project_hash=proj_hash,
                        container_name=name,
                        mitmweb_port=port,
                        mitmweb_url=url,
                        is_healthy=is_healthy,
                        active_clients=clients,
                    )
                )

    return sorted(proxies, key=lambda p: p.project_name)
