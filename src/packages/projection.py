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


def get_mcp_servers_dict(manifests: list[PackageManifest]) -> dict[str, dict[str, Any]]:
    """Extract and compile MCP server configurations from active package manifests."""
    servers: dict[str, dict[str, Any]] = {}
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
    return servers


def aggregate_egress_hosts(manifests: list[PackageManifest]) -> list[str]:
    """Aggregate all required network egress hosts across active packages."""
    hosts: set[str] = set()
    for m in manifests:
        hosts.update(m.egress.allow_hosts)
    return sorted(hosts)


def aggregate_token_replacers(manifests: list[PackageManifest]) -> list[dict[str, Any]]:
    """Aggregate token replacement redaction rules from active packages."""
    rules: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for m in manifests:
        for r in m.token_replacer:
            if r.name not in seen_names:
                seen_names.add(r.name)
                hostnames = (
                    list(r.hostnames)
                    if r.hostnames
                    else (list(m.egress.allow_hosts) if m.egress.allow_hosts else ["*"])
                )
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
    return rules


def aggregate_runtime_privileges(manifests: list[PackageManifest]) -> dict[str, Any]:
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

    for m in manifests:
        devices.update(m.runtime.devices)
        cap_add.update(m.runtime.cap_add)
        sysctl.update(m.runtime.sysctl)
        env.update(m.runtime.env)
        shadow_paths.update(m.runtime.shadow_paths)
        subuid_ranges.extend(m.runtime.subuid_ranges)
        file_caps.extend(m.runtime.file_caps)
        if m.runtime.nested_containers:
            nested_containers = True
        if m.runtime.shm_size:
            max_shm = m.runtime.shm_size

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
