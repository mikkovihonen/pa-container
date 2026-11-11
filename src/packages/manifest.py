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
    packages: list[str] = field(default_factory=list)


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
    dependencies: list[str] = field(default_factory=list)


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
class FeatureConfig:
    """Optional capability feature specification for a package."""

    name: str = ""
    description: str = ""
    default: bool = False
    payload: PayloadConfig = field(default_factory=lambda: PayloadConfig(type="none"))
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    egress: EgressConfig = field(default_factory=EgressConfig)
    token_replacer: list[TokenReplacerRule] = field(default_factory=list)
    skill_fragment: str | None = None
    verification: VerificationConfig = field(default_factory=VerificationConfig)


@dataclass(frozen=True)
class CLICommandExtension:
    """CLI subcommand contributed by a capability package."""

    name: str
    help: str = ""
    handler: str = ""


@dataclass(frozen=True)
class CLIFlagExtension:
    """CLI argument flag contributed by a capability package."""

    name: str
    type: str = "str"
    default: Any = None
    help: str = ""


@dataclass(frozen=True)
class ExtensionConfig:
    """CLI subcommands and flags exposed by a capability package."""

    entrypoint: str | None = None
    driver_class: str | None = None
    commands: list[CLICommandExtension] = field(default_factory=list)
    flags: list[CLIFlagExtension] = field(default_factory=list)
    config_key: str = ""


@dataclass(frozen=True)
class SecretMappingConfig:
    """Declarative secret mapping from OS keyring to proxy token replacer."""

    name: str
    keyring_account: str
    placeholder: str
    hosts: list[str] = field(default_factory=list)
    keyring_service: str = "pa-container"
    header: str | None = None
    pattern: str | None = None
    json_path: str | None = None
    required: bool = True


@dataclass(frozen=True)
class LifecycleHooksConfig:
    """Container lifecycle hook handlers."""

    on_container_configure: bool = False
    pre_start: bool = False
    post_start: bool = False
    on_stop: bool = False
    container_args: str | None = None


@dataclass(frozen=True)
class IntegrationConfig:
    """End-to-end integration test definition."""

    enabled: bool = False
    timeout_seconds: int = 120
    test_project: dict[str, Any] = field(default_factory=dict)
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
    build_memory_mib: int = 0
    payload: PayloadConfig = field(default_factory=lambda: PayloadConfig(type="none"))
    skill: SkillConfig = field(default_factory=SkillConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    egress: EgressConfig = field(default_factory=EgressConfig)
    token_replacer: list[TokenReplacerRule] = field(default_factory=list)
    secrets: list[SecretMappingConfig] = field(default_factory=list)
    verification: VerificationConfig = field(default_factory=VerificationConfig)
    features: dict[str, FeatureConfig] = field(default_factory=dict)
    extension: ExtensionConfig = field(default_factory=ExtensionConfig)
    hooks: LifecycleHooksConfig = field(default_factory=LifecycleHooksConfig)
    integration: IntegrationConfig = field(default_factory=IntegrationConfig)
    cli_flags: list[str] = field(default_factory=list)

    @property
    def all_cli_flags(self) -> list[str]:
        """All CLI flags contributed by this package (from cli_flags or extension.flags)."""
        flags = list(self.cli_flags)
        for fl in self.extension.flags:
            if fl.name not in flags:
                flags.append(fl.name)
        return flags


def _parse_payload(payload_data: dict[str, Any]) -> PayloadConfig:
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
    packages_raw = payload_data.get("packages") or []
    packages = [str(p).strip() for p in packages_raw if str(p).strip()] if isinstance(packages_raw, list) else []
    if payload_type == "distro_package" and not packages:
        raise ValueError("Payload of type 'distro_package' must specify at least one package in 'packages'")
    return PayloadConfig(
        type=payload_type,
        platforms=platforms,
        script=payload_data.get("script"),
        build_deps=list(payload_data.get("build_deps") or []),
        build_packages=list(payload_data.get("build_packages") or []),
        env=dict(payload_data.get("env") or {}),
        outputs=list(payload_data.get("outputs") or []),
        packages=packages,
    )


def _parse_skill(skill_data: dict[str, Any]) -> SkillConfig:
    return SkillConfig(
        enabled=bool(skill_data.get("enabled", False)),
        source=str(skill_data.get("source", "skill/SKILL.md")),
        target_agents=list(skill_data.get("target_agents") or ["all"]),
    )


def _parse_mcp(mcp_data: dict[str, Any], default_server_id: str) -> MCPConfig:
    return MCPConfig(
        enabled=bool(mcp_data.get("enabled", False)),
        server_id=str(mcp_data.get("server_id", default_server_id)),
        transport=str(mcp_data.get("transport", "stdio")),
        command=str(mcp_data.get("command", "")),
        args=list(mcp_data.get("args") or []),
        env=dict(mcp_data.get("env") or {}),
        port=mcp_data.get("port"),
    )


def _parse_runtime(runtime_data: dict[str, Any]) -> RuntimeConfig:
    return RuntimeConfig(
        devices=list(runtime_data.get("devices") or []),
        cap_add=list(runtime_data.get("cap_add") or []),
        sysctl=dict(runtime_data.get("sysctl") or {}),
        shm_size=runtime_data.get("shm_size"),
        nested_containers=bool(runtime_data.get("nested_containers", False)),
        env=dict(runtime_data.get("env") or {}),
        shadow_paths=list(runtime_data.get("shadow_paths") or []),
        subuid_ranges=list(runtime_data.get("subuid_ranges") or []),
        file_caps=list(runtime_data.get("file_caps") or []),
        dependencies=list(runtime_data.get("dependencies") or []),
    )


def _parse_egress(egress_data: dict[str, Any]) -> EgressConfig:
    return EgressConfig(
        allow_hosts=list(egress_data.get("allow_hosts") or []),
    )


def _parse_token_replacers(tr_data: Any) -> list[TokenReplacerRule]:
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
    return tr_rules


def _parse_secrets(secrets_data: Any) -> list[SecretMappingConfig]:
    if not isinstance(secrets_data, list):
        return []
    result: list[SecretMappingConfig] = []
    for item in secrets_data:
        if isinstance(item, dict) and "name" in item and "keyring_account" in item and "placeholder" in item:
            hosts_raw = item.get("hosts") or []
            hosts = [str(h).strip() for h in hosts_raw if str(h).strip()] if isinstance(hosts_raw, list) else []
            result.append(
                SecretMappingConfig(
                    name=str(item["name"]),
                    keyring_account=str(item["keyring_account"]),
                    placeholder=str(item["placeholder"]),
                    hosts=hosts,
                    keyring_service=str(item.get("keyring_service", "pa-container")),
                    header=str(item["header"]) if item.get("header") else None,
                    pattern=str(item["pattern"]) if item.get("pattern") else None,
                    json_path=str(item["json_path"]) if item.get("json_path") else None,
                    required=bool(item.get("required", True)),
                )
            )
    return result


def _parse_verification(ver_data: dict[str, Any]) -> VerificationConfig:
    return VerificationConfig(
        command=str(ver_data.get("command", "")),
        expected_output_contains=ver_data.get("expected_output_contains"),
    )


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

    payload = _parse_payload(data.get("payload") or {})
    skill = _parse_skill(data.get("skill") or {})
    mcp = _parse_mcp(data.get("mcp") or {}, default_server_id=name)
    runtime = _parse_runtime(data.get("runtime") or {})
    egress = _parse_egress(data.get("egress") or {})
    tr_rules = _parse_token_replacers(data.get("token_replacer") or {})
    verification = _parse_verification(data.get("verification") or {})

    # Features
    features_raw = data.get("features") or {}
    features: dict[str, FeatureConfig] = {}
    if isinstance(features_raw, dict):
        for feat_name, feat_dict in features_raw.items():
            if isinstance(feat_dict, dict):
                features[feat_name] = FeatureConfig(
                    name=feat_name,
                    description=str(feat_dict.get("description", "")),
                    default=bool(feat_dict.get("default", False)),
                    payload=_parse_payload(feat_dict.get("payload") or {}),
                    runtime=_parse_runtime(feat_dict.get("runtime") or {}),
                    mcp=_parse_mcp(feat_dict.get("mcp") or {}, default_server_id=f"{name}-{feat_name}"),
                    egress=_parse_egress(feat_dict.get("egress") or {}),
                    token_replacer=_parse_token_replacers(feat_dict.get("token_replacer") or {}),
                    skill_fragment=feat_dict.get("skill_fragment"),
                    verification=_parse_verification(feat_dict.get("verification") or {}),
                )

    # Extension
    ext_data = data.get("extension") or {}
    commands: list[CLICommandExtension] = []
    flags: list[CLIFlagExtension] = []
    entrypoint: str | None = None
    driver_class: str | None = None
    if isinstance(ext_data, dict):
        if "entrypoint" in ext_data and ext_data["entrypoint"]:
            entrypoint = str(ext_data["entrypoint"]).strip()
        if "driver_class" in ext_data and ext_data["driver_class"]:
            driver_class = str(ext_data["driver_class"]).strip()
        for cmd_raw in ext_data.get("commands") or []:
            if isinstance(cmd_raw, dict) and "name" in cmd_raw:
                commands.append(
                    CLICommandExtension(
                        name=str(cmd_raw["name"]),
                        help=str(cmd_raw.get("help", "")),
                        handler=str(cmd_raw.get("handler", "")),
                    )
                )
        for flg_raw in ext_data.get("flags") or []:
            if isinstance(flg_raw, dict) and "name" in flg_raw:
                flags.append(
                    CLIFlagExtension(
                        name=str(flg_raw["name"]),
                        type=str(flg_raw.get("type", "str")),
                        default=flg_raw.get("default"),
                        help=str(flg_raw.get("help", "")),
                    )
                )
    extension = ExtensionConfig(
        entrypoint=entrypoint,
        driver_class=driver_class,
        commands=commands,
        flags=flags,
        config_key=str(ext_data.get("config_key", "")),
    )

    # Lifecycle & Hooks
    lifecycle_data = data.get("lifecycle") or {}
    hooks_data = (lifecycle_data.get("hooks") or data.get("hooks") or {}) if isinstance(lifecycle_data, dict) else {}
    if not isinstance(hooks_data, dict):
        hooks_data = {}
    hooks = LifecycleHooksConfig(
        on_container_configure=bool(hooks_data.get("on_container_configure", False)),
        pre_start=bool(hooks_data.get("pre_start", False)),
        post_start=bool(hooks_data.get("post_start", False)),
        on_stop=bool(hooks_data.get("on_stop", False)),
        container_args=str(hooks_data["container_args"]) if isinstance(hooks_data.get("container_args"), str) else None,
    )

    secrets = _parse_secrets(data.get("secrets") or [])

    # Integration
    int_data = data.get("integration") or {}
    integration = IntegrationConfig(
        enabled=bool(int_data.get("enabled", False)),
        timeout_seconds=int(int_data.get("timeout_seconds", 120)),
        test_project=dict(int_data.get("test_project") or {}),
        command=str(int_data.get("command", "")),
        expected_output_contains=int_data.get("expected_output_contains"),
    )

    build_memory_mib = int(data.get("build_memory_mib") or 0)

    return PackageManifest(
        schema_version=schema_version,
        name=name,
        version=version,
        description=description,
        category=category,
        license=license_str,
        build_memory_mib=build_memory_mib,
        payload=payload,
        skill=skill,
        mcp=mcp,
        runtime=runtime,
        egress=egress,
        token_replacer=tr_rules,
        secrets=secrets,
        verification=verification,
        features=features,
        extension=extension,
        hooks=hooks,
        integration=integration,
        cli_flags=[str(f) for f in (data.get("cli_flags") or []) if isinstance(f, (str, int, float))],
    )


def load_package_manifest(path: Path) -> PackageManifest:
    """Load and parse package.yaml from disk."""
    if not path.is_file():
        raise FileNotFoundError(f"Package manifest not found: {path}")
    data = load_yaml_strict(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"Invalid package manifest format in {path}: expected YAML mapping")
    return parse_package_manifest(data, path=path)
