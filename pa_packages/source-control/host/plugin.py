from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, cast

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from packages.plugin import ACPPlugin, ContainerRunSpec, RunContext, SecretTokenMapping

from .source_control import (
    resolve_source_control_tokens,
)

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import PackageSecretDeclaration, ProjectConfig
    from packages.manifest import PackageManifest

    from .types import SourceControlConfig

logger = get_category_logger(__name__, LogCategory.SECURITY)


class SourceControlPlugin(ACPPlugin):
    """ACP Plugin for multi-provider source control authentication and Git credentials."""

    def __init__(
        self,
        manifest: PackageManifest,
        package_dir: Path,
        project_dir: Path | None = None,
    ) -> None:
        super().__init__(manifest, package_dir, project_dir)
        self.sc_cfg: SourceControlConfig | None = None
        self.resolved_tokens: dict[str, str] = {}

    def contribute_config_schema(self) -> dict[str, Any]:
        """Contribute validation schema dictionary for the 'source-control' package config."""
        return {
            "type": dict,
            "required": False,
            "keys": {
                "auto_detect_host_cli": {"type": bool, "required": False},
                "setup_git_credentials": {"type": bool, "required": False},
            },
        }

    def get_secret_mappings(self, config: ProjectConfig) -> list[SecretTokenMapping]:
        """Contribute declarative secret mappings for proxy token redaction."""
        pkgs_list = config.get("packages") or []
        sc_secrets: list[PackageSecretDeclaration] = []
        if isinstance(pkgs_list, list):
            for item in pkgs_list:
                if isinstance(item, dict) and "source-control" in item:
                    val = item["source-control"]
                    if isinstance(val, dict):
                        sc_secrets = val.get("secrets") or []
                    break

        mappings: list[SecretTokenMapping] = []
        provider_hosts: dict[str, tuple[str, ...]] = {
            "github": ("api.github.com", "*.github.com"),
            "gitlab": ("gitlab.com", "*.gitlab.com"),
            "forgejo": ("gitea.com", "codeberg.org"),
            "azure_devops": ("dev.azure.com", "*.visualstudio.com"),
            "bitbucket": ("bitbucket.org", "api.bitbucket.org"),
            "gitcafe": ("gitcafe.com", "*.gitcafe.com"),
        }

        for s in sc_secrets:
            if not isinstance(s, dict):
                continue
            prov_name = str(s.get("name", "")).strip()
            account_name = str(s.get("account", "")).strip()
            if not prov_name or not account_name:
                continue
            hosts = provider_hosts.get(prov_name)
            if not hosts:
                continue

            mappings.append(
                SecretTokenMapping(
                    name=f"{prov_name}-token",
                    keyring_account=account_name,
                    placeholder=f"[REDACTED_{prov_name.upper()}_TOKEN]",
                    hosts=hosts,
                    keyring_service="pa-container",
                    required=True,
                )
            )

        return mappings

    def on_run_init(self, context: RunContext) -> None:
        """Resolve source control tokens and register 'source-control' mode."""
        cfg = context.get_package_config("source-control")
        if not cfg and self.manifest:
            cfg = dict(self.manifest.config)
        self.sc_cfg = cast("SourceControlConfig", cfg)

        context.add_mode("source-control")
        secrets = context.get_package_secrets("source-control")
        tokens = resolve_source_control_tokens(
            secrets=secrets,
            log=logger,
        )
        self.resolved_tokens = tokens
        context.set_attribute("source_control.tokens", tokens)

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        context: RunContext,
    ) -> None:
        """Inject resolved source control tokens and setup flag into container environment."""
        cfg = self.sc_cfg or context.get_package_config("source-control")

        # Inject resolved tokens
        for k, v in self.resolved_tokens.items():
            spec.env[k] = v

        # Configure git credential helper behavior
        setup_git = cfg.get("setup_git_credentials", True)
        spec.env["SETUP_GIT_CREDENTIALS"] = "true" if setup_git else "false"
        spec.env["SETUP_GIT_CREDENTIALS"] = "true" if setup_git else "false"
