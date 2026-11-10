from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

sys.dont_write_bytecode = True

from yaml_strict import load_yaml_strict

"""Package manifest data models and strict parser for Agent Capability Packages (ACPs)."""


@dataclass(frozen=True)
class PlatformDownload:
    """Download metadata for a specific platform architecture."""

    url: str
    sha256: str
    extract_map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PayloadConfig:
    """Application payload specification (binary download, build script, or distro package)."""

    type: str  # "binary_download", "build_script", "distro_package", "none"
    platforms: dict[str, PlatformDownload] = field(default_factory=dict)
    script: str | None = None
    build_deps: list[str] = field(default_factory=list)
    build_packages: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    outputs: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class SkillConfig:
    """Agent skill prompt metadata."""

    enabled: bool = False
    source: str = "skill/SKILL.md"
    target_agents: list[str] = field(default_factory=lambda: ["all"])


@dataclass(frozen=True)
class MCPConfig:
    """Model Context Protocol (MCP) server configuration."""

    enabled: bool = False
    server_id: str = ""
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    port: int | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    """Container runtime privileges, devices, capabilities, and system configuration."""

    devices: list[str] = field(default_factory=list)
    cap_add: list[str] = field(default_factory=list)
    sysctl: dict[str, str] = field(default_factory=dict)
    shm_size: str | None = None
    nested_containers: bool = False
    env: dict[str, str] = field(default_factory=dict)
    shadow_paths: list[str] = field(default_factory=list)
    subuid_ranges: list[str] = field(default_factory=list)
    file_caps: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class EgressConfig:
    """Network egress policy (hosts allowed through proxy)."""

    allow_hosts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TokenReplacerRule:
    """Sensitive token redaction rule for proxy inspection."""

    name: str
    hostnames: list[str] = field(default_factory=list)
    content_patterns: list[dict[str, Any]] = field(default_factory=list)
    replace_with: dict[str, str] = field(default_factory=dict)
    header: str | None = None
    pattern: str = ""
    replacement: str = ""


@dataclass(frozen=True)
class VerificationConfig:
    """In-container verification command to run after installation."""

    command: str = ""
    expected_output_contains: str | None = None


@dataclass(frozen=True)
class PackageManifest:
    """Declarative specification for an Agent Capability Package (ACP)."""

    schema_version: str
    name: str
    version: str
    description: str = ""
    category: str = "devtools"
    license: str = "unknown"
    payload: PayloadConfig = field(default_factory=lambda: PayloadConfig(type="none"))
    skill: SkillConfig = field(default_factory=SkillConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    egress: EgressConfig = field(default_factory=EgressConfig)
    token_replacer: list[TokenReplacerRule] = field(default_factory=list)
    verification: VerificationConfig = field(default_factory=VerificationConfig)


def parse_package_manifest(data: dict[str, Any], path: Path | None = None) -> PackageManifest:
    """Parse and validate a dictionary into a PackageManifest dataclass."""
    origin = f" in {path}" if path else ""

    schema_version = str(data.get("schema_version", "2.0.0"))
    name = data.get("name")
    if not name or not isinstance(name, str):
        raise ValueError(f"Missing required 'name' string field in package manifest{origin}")
    version = data.get("version")
    if not version or not isinstance(version, str):
        raise ValueError(f"Missing required 'version' string field in package manifest{origin}")

    description = str(data.get("description", ""))
    category = str(data.get("category", "devtools"))
    license_str = str(data.get("license", "unknown"))

    # Payload
    payload_data = data.get("payload") or {}
    payload_type = str(payload_data.get("type", "none"))
    platforms_raw = payload_data.get("platforms") or {}
    platforms: dict[str, PlatformDownload] = {}
    if isinstance(platforms_raw, dict):
        for arch, arch_data in platforms_raw.items():
            if isinstance(arch_data, dict):
                platforms[arch] = PlatformDownload(
                    url=str(arch_data.get("url", "")),
                    sha256=str(arch_data.get("sha256", "")),
                    extract_map=dict(arch_data.get("extract_map") or {}),
                )
    payload = PayloadConfig(
        type=payload_type,
        platforms=platforms,
        script=payload_data.get("script"),
        build_deps=list(payload_data.get("build_deps") or []),
        build_packages=list(payload_data.get("build_packages") or []),
        env=dict(payload_data.get("env") or {}),
        outputs=list(payload_data.get("outputs") or []),
    )

    # Skill
    skill_data = data.get("skill") or {}
    skill = SkillConfig(
        enabled=bool(skill_data.get("enabled", False)),
        source=str(skill_data.get("source", "skill/SKILL.md")),
        target_agents=list(skill_data.get("target_agents") or ["all"]),
    )

    # MCP
    mcp_data = data.get("mcp") or {}
    mcp = MCPConfig(
        enabled=bool(mcp_data.get("enabled", False)),
        server_id=str(mcp_data.get("server_id", name)),
        transport=str(mcp_data.get("transport", "stdio")),
        command=str(mcp_data.get("command", "")),
        args=list(mcp_data.get("args") or []),
        env=dict(mcp_data.get("env") or {}),
        port=mcp_data.get("port"),
    )

    # Runtime
    runtime_data = data.get("runtime") or {}
    runtime = RuntimeConfig(
        devices=list(runtime_data.get("devices") or []),
        cap_add=list(runtime_data.get("cap_add") or []),
        sysctl=dict(runtime_data.get("sysctl") or {}),
        shm_size=runtime_data.get("shm_size"),
        nested_containers=bool(runtime_data.get("nested_containers", False)),
        env=dict(runtime_data.get("env") or {}),
        shadow_paths=list(runtime_data.get("shadow_paths") or []),
        subuid_ranges=list(runtime_data.get("subuid_ranges") or []),
        file_caps=list(runtime_data.get("file_caps") or []),
    )

    # Egress
    egress_data = data.get("egress") or {}
    egress = EgressConfig(
        allow_hosts=list(egress_data.get("allow_hosts") or []),
    )

    # Token Replacer
    tr_data = data.get("token_replacer") or {}
    tr_rules: list[TokenReplacerRule] = []
    rules_raw = tr_data.get("rules") if isinstance(tr_data, dict) else tr_data
    if isinstance(rules_raw, list):
        for r in rules_raw:
            if isinstance(r, dict):
                hostnames = list(r.get("hostnames") or [])
                content_patterns = [dict(cp) for cp in r.get("content_patterns") or [] if isinstance(cp, dict)]
                replace_with = dict(r.get("replace_with") or {})
                header = r.get("header")
                pattern = str(r.get("pattern", ""))
                replacement = str(r.get("replacement", ""))

                if not content_patterns:
                    if header:
                        content_patterns = [{"field": "headers", "header_name": header, "regex": pattern or ".*"}]
                    elif pattern:
                        content_patterns = [{"field": "body.raw", "regex": pattern}]

                if not replace_with:
                    replace_with = {
                        "strategy": "static",
                        "value": replacement or f"${{ENV:{str(r.get('name', '')).upper().replace('-', '_')}}}",
                    }

                tr_rules.append(
                    TokenReplacerRule(
                        name=str(r.get("name", "")),
                        hostnames=hostnames,
                        content_patterns=content_patterns,
                        replace_with=replace_with,
                        header=header,
                        pattern=pattern,
                        replacement=replacement,
                    )
                )

    # Verification
    ver_data = data.get("verification") or {}
    verification = VerificationConfig(
        command=str(ver_data.get("command", "")),
        expected_output_contains=ver_data.get("expected_output_contains"),
    )

    return PackageManifest(
        schema_version=schema_version,
        name=name,
        version=version,
        description=description,
        category=category,
        license=license_str,
        payload=payload,
        skill=skill,
        mcp=mcp,
        runtime=runtime,
        egress=egress,
        token_replacer=tr_rules,
        verification=verification,
    )


def load_package_manifest(path: Path) -> PackageManifest:
    """Load and parse package.yaml from disk."""
    if not path.is_file():
        raise FileNotFoundError(f"Package manifest not found: {path}")
    data = load_yaml_strict(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Invalid package manifest format in {path}: expected YAML mapping")
    return parse_package_manifest(data, path=path)
