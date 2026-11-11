from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from packages.plugin import ACPPlugin, ContainerRunSpec, RunContext, SecretTokenMapping

from .source_control import (
    parse_source_control_config_dict,
    resolve_source_control_tokens,
)

if TYPE_CHECKING:
    from pathlib import Path

    from config_types import ProjectConfig
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
        """Contribute validation schema dictionary for the 'source_control' section in config.yaml."""
        return {
            "type": dict,
            "required": False,
            "keys": {
                "enabled": {"type": bool, "required": False},
                "auto_detect_host_cli": {"type": bool, "required": False},
                "setup_git_credentials": {"type": bool, "required": False},
                "providers": {"type": dict, "required": False},
            },
        }

    def get_secret_mappings(self, config: ProjectConfig) -> list[SecretTokenMapping]:
        """Contribute declarative secret mappings for proxy token redaction."""
        raw_sc = config.get("source_control")
        cfg = parse_source_control_config_dict(raw_sc)
        if not cfg["enabled"]:
            return []

        providers = cfg.get("providers", {})
        mappings: list[SecretTokenMapping] = []

        provider_hosts: dict[str, tuple[str, ...]] = {
            "github": ("api.github.com", "*.github.com"),
            "gitlab": ("gitlab.com", "*.gitlab.com"),
            "forgejo": ("gitea.com", "codeberg.org"),
            "azure_devops": ("dev.azure.com", "*.visualstudio.com"),
            "bitbucket": ("bitbucket.org", "api.bitbucket.org"),
            "gitcafe": ("gitcafe.com", "*.gitcafe.com"),
        }
        default_accounts: dict[str, str] = {
            "github": "GH_TOKEN",
            "gitlab": "GITLAB_TOKEN",
            "forgejo": "GITEA_TOKEN",
            "azure_devops": "AZURE_DEVOPS_EXT_PAT",
            "bitbucket": "BITBUCKET_TOKEN",
            "gitcafe": "GITCAFE_TOKEN",
        }

        for prov_name, hosts in provider_hosts.items():
            p_cfg = providers.get(prov_name, {})
            acct = p_cfg.get("keyring_var")
            account_name = str(acct if isinstance(acct, str) else (acct[0] if acct else default_accounts[prov_name]))
            svc = str(p_cfg.get("keyring_service") or "pa-container")

            mappings.append(
                SecretTokenMapping(
                    name=f"{prov_name}-token",
                    keyring_account=account_name,
                    placeholder=f"[REDACTED_{prov_name.upper()}_TOKEN]",
                    hosts=hosts,
                    keyring_service=svc,
                    required=False,
                )
            )

        return mappings

    def on_run_init(self, context: RunContext) -> None:
        """Resolve source control tokens and register 'source-control' mode."""
        raw_sc = context.config.get("source_control") if context.config else None
        cfg = parse_source_control_config_dict(raw_sc)
        self.sc_cfg = cfg

        if cfg["enabled"]:
            context.add_mode("source-control")
            tokens = resolve_source_control_tokens(
                config_dir=(self.project_dir / ".pa-container") if self.project_dir else None,
                log=logger,
                raw_config=dict(context.config) if context.config else None,
            )
            self.resolved_tokens = tokens
            context.set_attribute("source_control.tokens", tokens)

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        context: RunContext,
    ) -> None:
        """Inject resolved source control tokens and setup flag into container environment."""
        if self.sc_cfg is None:
            raw_sc = context.config.get("source_control") if context.config else None
            self.sc_cfg = parse_source_control_config_dict(raw_sc)

        # Inject resolved tokens
        for k, v in self.resolved_tokens.items():
            spec.env[k] = v

        # Configure git credential helper behavior
        setup_git = self.sc_cfg.get("setup_git_credentials", True)
        spec.env["SETUP_GIT_CREDENTIALS"] = "true" if setup_git else "false"
