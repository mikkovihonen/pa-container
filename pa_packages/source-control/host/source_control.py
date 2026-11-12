from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.dont_write_bytecode = True

"""Source control authentication and token lifecycle management.

Resolves authentication credentials for source control providers (GitHub, GitLab,
Forgejo/Gitea, Azure DevOps, Bitbucket, GitCafe) exclusively from the host OS Keyring
(or active host CLI session if auto_detect_host_cli is explicitly enabled).

Neither .env files nor host environment variables are accepted as credential stores.
"""

if TYPE_CHECKING:
    import logging
    from collections.abc import Mapping

    from packages.manifest import PackageManifest

    from .types import SourceControlConfig

from logging_driver import LogCategory, get_category_logger
from network import load_project_config
from secret_store import DEFAULT_KEYRING_SERVICE, get_keyring_secret

logger = get_category_logger(__name__, LogCategory.SECURITY)


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    canonical_env_var: str
    default_keyring_vars: tuple[str, ...]
    host_cli_cmd: tuple[str, ...] | None


PROVIDER_DEFINITIONS: tuple[ProviderDefinition, ...] = (
    ProviderDefinition(
        name="github",
        canonical_env_var="GH_TOKEN",
        default_keyring_vars=("GH_TOKEN",),
        host_cli_cmd=("gh", "auth", "token"),
    ),
    ProviderDefinition(
        name="gitlab",
        canonical_env_var="GITLAB_TOKEN",
        default_keyring_vars=("GITLAB_TOKEN",),
        host_cli_cmd=None,
    ),
    ProviderDefinition(
        name="forgejo",
        canonical_env_var="GITEA_TOKEN",
        default_keyring_vars=("GITEA_TOKEN",),
        host_cli_cmd=None,
    ),
    ProviderDefinition(
        name="azure_devops",
        canonical_env_var="AZURE_DEVOPS_EXT_PAT",
        default_keyring_vars=("AZURE_DEVOPS_EXT_PAT",),
        host_cli_cmd=(
            "az",
            "account",
            "get-access-token",
            "--resource",
            "499b84de-3277-4e70-9c43-e57d724c06e7",
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ),
    ),
    ProviderDefinition(
        name="bitbucket",
        canonical_env_var="BITBUCKET_TOKEN",
        default_keyring_vars=("BITBUCKET_TOKEN",),
        host_cli_cmd=None,
    ),
    ProviderDefinition(
        name="gitcafe",
        canonical_env_var="GITCAFE_TOKEN",
        default_keyring_vars=("GITCAFE_TOKEN",),
        host_cli_cmd=None,
    ),
)


def mask_token(token: str) -> str:
    """Mask a sensitive token string for safe logging."""
    if not token:
        return ""
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


# In-container environment variable names that must never be overridden via
# the 'agent.env' project configuration. These carry provider token
# placeholders injected by the source-control plugin.
GUARDED_TOKEN_ENV_VARS: frozenset[str] = frozenset(
    {
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GITLAB_TOKEN",
        "GLAB_TOKEN",
        "GITEA_TOKEN",
        "AZURE_DEVOPS_EXT_PAT",
        "BITBUCKET_TOKEN",
        "GITCAFE_TOKEN",
    }
)


def resolve_source_control_placeholder_env(
    secrets: list[Any],
    manifest: PackageManifest | None = None,
) -> dict[str, str]:
    """Map declared source-control secret slots to in-container placeholder values.

    Only placeholders derived from the package manifest ever enter the agent
    container. The host-side proxy substitutes the real tokens (pulled from the
    OS keyring / trusted host-side registry) when requests leave the container.

    Args:
        secrets: Declared secret slots (``{"name": ..., "account": ...}`` dicts).
        manifest: The source-control package manifest carrying feature secrets
            with ``placeholder`` fields. May be None (placeholders fall back to
            ``<CANONICAL_ENV_VAR>_PLACEHOLDER``).

    Returns:
        A mapping of canonical environment variable name to placeholder value.
    """
    placeholders_by_slot: dict[str, str] = {}
    if manifest is not None:
        for sec in list(manifest.secrets) + [s for f in manifest.features.values() for s in f.secrets]:
            if sec.name and sec.placeholder:
                placeholders_by_slot[sec.name] = sec.placeholder

    provider_by_name = {p.name: p for p in PROVIDER_DEFINITIONS}
    env: dict[str, str] = {}
    for item in secrets:
        if not isinstance(item, dict):
            continue
        slot_name = str(item.get("name", "")).strip()
        provider = provider_by_name.get(slot_name)
        if not provider:
            continue
        env[provider.canonical_env_var] = placeholders_by_slot.get(
            slot_name, f"{provider.canonical_env_var}_PLACEHOLDER"
        )
    return env


def parse_source_control_config_dict(raw_section: Any) -> SourceControlConfig:
    """Parse and normalize a raw source_control dict."""
    section: dict[str, Any] = dict(raw_section) if isinstance(raw_section, dict) else {}

    for key in ("enabled", "auto_detect_host_cli", "setup_git_credentials"):
        if key in section and not isinstance(section[key], bool):
            raise ValueError(f"Invalid 'source_control.{key}': expected bool, got {type(section[key]).__name__}")

    enabled_val = section.get("enabled", False)
    auto_detect_val = section.get("auto_detect_host_cli", False)
    setup_git_val = section.get("setup_git_credentials", True)
    providers_val = section.get("providers", {})

    return {
        "enabled": bool(enabled_val),
        "auto_detect_host_cli": bool(auto_detect_val),
        "setup_git_credentials": bool(setup_git_val),
        "providers": providers_val if isinstance(providers_val, dict) else {},
    }


def read_source_control_config(
    config_dir: Path | None = None,
    raw_config: dict[str, Any] | None = None,
) -> SourceControlConfig:
    """Read and normalize the ``source_control`` section from config.yaml or raw config dict."""
    config = raw_config if raw_config is not None else load_project_config(config_dir)
    return parse_source_control_config_dict(config.get("source_control"))


def _probe_host_cli(cmd: tuple[str, ...]) -> str | None:
    """Execute host CLI command to retrieve authentication token."""
    bin_name = cmd[0]
    if not shutil.which(bin_name):
        return None
    try:
        res = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0:
            token = res.stdout.strip()
            return token if token else None
    except Exception as e:
        logger.debug(f"Host CLI probe failed for {cmd}: {e}")
    return None


def resolve_source_control_tokens(
    config_dir_or_secrets: list[Any] | Path | None = None,
    log: logging.Logger | logging.LoggerAdapter[Any] | None = None,
    config_dir: Path | None = None,
    raw_config: Mapping[str, Any] | None = None,
    secrets: list[Any] | None = None,
    feature_configs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Resolve real tokens for all source control providers exclusively from declared secrets.

    Returns a mapping of canonical environment variable names to real token
    values. The values never enter the agent container: they are registered in
    the trusted host-side secret registry so the proxy can substitute the
    in-container placeholders in outgoing requests.
    """
    sc_log = log or logger
    secret_list: list[Any] = []
    effective_config_dir: Path | None = config_dir

    if isinstance(config_dir_or_secrets, list):
        secret_list = list(config_dir_or_secrets)
    elif isinstance(config_dir_or_secrets, Path):
        effective_config_dir = config_dir_or_secrets
    elif secrets:
        secret_list = list(secrets)

    auto_detect_host_cli = False
    feat_cfgs: dict[str, dict[str, Any]] = dict(feature_configs or {})
    cfg = (
        raw_config
        if raw_config is not None
        else (load_project_config(effective_config_dir) if effective_config_dir else {})
    )
    if cfg:
        pkgs = cfg.get("packages") or []
        if isinstance(pkgs, list):
            for item in pkgs:
                if isinstance(item, dict) and "source-control" in item:
                    val = item["source-control"]
                    if isinstance(val, dict):
                        if not secret_list:
                            secret_list.extend(val.get("secrets") or [])
                            feats = val.get("features") or []
                            if isinstance(feats, list):
                                for f in feats:
                                    if isinstance(f, dict) and len(f) == 1:
                                        f_name, f_val = next(iter(f.items()))
                                        if isinstance(f_val, dict):
                                            secret_list.extend(f_val.get("secrets") or [])
                                            if f_name not in feat_cfgs and "config" in f_val:
                                                feat_cfgs[f_name] = dict(f_val["config"] or {})
                        pkg_cfg = val.get("config") or {}
                        if isinstance(pkg_cfg, dict):
                            auto_detect_host_cli = bool(pkg_cfg.get("auto_detect_host_cli", False))
                    break

    resolved_env: dict[str, str] = {}
    provider_by_name = {p.name: p for p in PROVIDER_DEFINITIONS}

    for item in secret_list:
        if not isinstance(item, dict):
            continue
        slot_name = str(item.get("name", "")).strip()
        account = str(item.get("account", "")).strip()
        if not slot_name or not account:
            continue
        provider = provider_by_name.get(slot_name)
        if not provider:
            continue

        prov_auto_detect = auto_detect_host_cli
        prov_feat_cfg = feat_cfgs.get(provider.name) or feat_cfgs.get(provider.name.replace("_", "-"))
        if prov_feat_cfg and "auto_detect_host_cli" in prov_feat_cfg:
            prov_auto_detect = bool(prov_feat_cfg["auto_detect_host_cli"])

        secret = get_keyring_secret(account, service=DEFAULT_KEYRING_SERVICE)
        if not secret and prov_auto_detect and provider.host_cli_cmd:
            cli_token = _probe_host_cli(provider.host_cli_cmd)
            if cli_token:
                secret = cli_token
                sc_log.info(f"Resolved {provider.name} source control token from host CLI: {mask_token(secret)}")

        if secret:
            token = secret.strip()
            sc_log.info(
                f"Resolved {provider.name} source control token from OS keyring (account='{account}'): {mask_token(token)}"
            )
            resolved_env[provider.canonical_env_var] = token
        else:
            raise ValueError(
                f"Required secret for '{provider.name}' (keyring account '{account}') was not found in OS Keyring. "
                f"Run: uv run keyring set {DEFAULT_KEYRING_SERVICE} {account}"
            )

    return resolved_env
