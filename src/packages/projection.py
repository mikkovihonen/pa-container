from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from packages.manifest import PackageManifest

sys.dont_write_bytecode = True

"""Runtime projection engine for Agent Capability Packages (ACPs).

Synthesizes agent-specific MCP server definitions, aggregates proxy egress allowlists,
compiles token replacer rules, and gathers container privilege requirements.
"""


def get_mcp_servers_dict(
    manifests: list[PackageManifest],
    active_features: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Extract and compile MCP server configurations from active package manifests and enabled features."""
    servers: dict[str, dict[str, Any]] = {}
    feats_map = active_features or {}
    for m in manifests:
        if m.mcp.enabled and m.mcp.command:
            server_entry: dict[str, Any] = {
                "command": m.mcp.command,
                "args": list(m.mcp.args),
            }
            if m.mcp.env:
                server_entry["env"] = dict(m.mcp.env)
            if m.mcp.transport:
                server_entry["transport"] = m.mcp.transport
            if m.mcp.port is not None:
                server_entry["port"] = m.mcp.port
            servers[m.mcp.server_id or m.name] = server_entry

        # Feature MCP servers
        enabled_feats = feats_map.get(m.name, [])
        for feat_name, feat in m.features.items():
            if (
                (feat_name in enabled_feats or (not enabled_feats and feat.default))
                and feat.mcp.enabled
                and feat.mcp.command
            ):
                f_server_entry: dict[str, Any] = {
                    "command": feat.mcp.command,
                    "args": list(feat.mcp.args),
                }
                if feat.mcp.env:
                    f_server_entry["env"] = dict(feat.mcp.env)
                if feat.mcp.transport:
                    f_server_entry["transport"] = feat.mcp.transport
                if feat.mcp.port is not None:
                    f_server_entry["port"] = feat.mcp.port
                servers[feat.mcp.server_id or f"{m.name}-{feat_name}"] = f_server_entry

    return servers


def aggregate_egress_hosts(
    manifests: list[PackageManifest],
    active_features: dict[str, list[str]] | None = None,
) -> list[str]:
    """Aggregate all required network egress hosts across active packages and enabled features."""
    hosts: set[str] = set()
    feats_map = active_features or {}
    for m in manifests:
        hosts.update(m.egress.allow_hosts)
        enabled_feats = feats_map.get(m.name, [])
        for feat_name, feat in m.features.items():
            if feat_name in enabled_feats or (not enabled_feats and feat.default):
                hosts.update(feat.egress.allow_hosts)
    return sorted(hosts)


def aggregate_token_replacers(
    manifests: list[PackageManifest],
    active_features: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate token replacement redaction rules from active packages and enabled features."""
    rules: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    feats_map = active_features or {}

    def _add_rule(r: Any, fallback_hosts: list[str]) -> None:
        if r.name not in seen_names:
            seen_names.add(r.name)
            hostnames = list(r.hostnames) if r.hostnames else (fallback_hosts if fallback_hosts else ["*"])
            rule_dict: dict[str, Any] = {
                "name": r.name,
                "hostnames": hostnames,
                "content_patterns": [dict(cp) for cp in r.content_patterns],
                "replace_with": dict(r.replace_with),
            }
            if r.header:
                rule_dict["header"] = r.header
            if r.pattern:
                rule_dict["pattern"] = r.pattern
            if r.replacement:
                rule_dict["replacement"] = r.replacement
            rules.append(rule_dict)

    for m in manifests:
        for r in m.token_replacer:
            _add_rule(r, list(m.egress.allow_hosts))
        enabled_feats = feats_map.get(m.name, [])
        for feat_name, feat in m.features.items():
            if feat_name in enabled_feats or (not enabled_feats and feat.default):
                for r in feat.token_replacer:
                    _add_rule(r, list(feat.egress.allow_hosts))

    return rules


def aggregate_runtime_privileges(
    manifests: list[PackageManifest],
    active_features: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Aggregate container runtime devices, capabilities, sysctls, and environment variables."""
    devices: set[str] = set()
    cap_add: set[str] = set()
    sysctl: dict[str, str] = {}
    env: dict[str, str] = {}
    shadow_paths: set[str] = set()
    subuid_ranges: list[str] = []
    file_caps: list[dict[str, str]] = []
    nested_containers = False
    max_shm: str | None = None
    feats_map = active_features or {}

    def _apply_runtime(rt: Any) -> None:
        nonlocal nested_containers, max_shm
        devices.update(rt.devices)
        cap_add.update(rt.cap_add)
        sysctl.update(rt.sysctl)
        env.update(rt.env)
        shadow_paths.update(rt.shadow_paths)
        subuid_ranges.extend(rt.subuid_ranges)
        file_caps.extend(rt.file_caps)
        if rt.nested_containers:
            nested_containers = True
        if rt.shm_size:
            max_shm = rt.shm_size

    for m in manifests:
        _apply_runtime(m.runtime)
        enabled_feats = feats_map.get(m.name, [])
        for feat_name, feat in m.features.items():
            if feat_name in enabled_feats or (not enabled_feats and feat.default):
                _apply_runtime(feat.runtime)

    return {
        "devices": sorted(devices),
        "cap_add": sorted(cap_add),
        "sysctl": sysctl,
        "env": env,
        "shadow_paths": sorted(shadow_paths),
        "subuid_ranges": subuid_ranges,
        "file_caps": file_caps,
        "nested_containers": nested_containers,
        "shm_size": max_shm,
    }
