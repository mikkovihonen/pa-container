from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, cast

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from packages.plugin import ACPPlugin, ContainerRunSpec, RunContext
from secret_store import register_resolved_secret

from .source_control import (
    GUARDED_TOKEN_ENV_VARS,
    resolve_source_control_placeholder_env,
    resolve_source_control_tokens,
)

if TYPE_CHECKING:
    from pathlib import Path

    from packages.manifest import PackageManifest

    from .types import SourceControlConfig

logger = get_category_logger(__name__, LogCategory.SECURITY)


class SourceControlPlugin(ACPPlugin):
    """ACP Plugin for multi-provider source control authentication and Git credentials.

    Security model: the agent container only ever sees placeholder token
    values (e.g. ``GH_TOKEN_PLACEHOLDER``). Real tokens are resolved host-side
    from the OS keyring (or a host CLI session) and registered in the trusted
    in-process secret registry so the proxy can substitute placeholders in
    outgoing HTTP traffic (see the ``token_replacer`` rules in package.yaml).
    """

    def __init__(
        self,
        manifest: PackageManifest,
        package_dir: Path,
        project_dir: Path | None = None,
    ) -> None:
        super().__init__(manifest, package_dir, project_dir)
        self.sc_cfg: SourceControlConfig | None = None
        self.resolved_tokens: dict[str, str] = {}
        self.placeholder_env: dict[str, str] = {}

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

    def contribute_feature_config_schema(self, feature_name: str) -> dict[str, Any] | None:
        """Contribute validation schema dictionary for source-control features."""
        return {
            "type": dict,
            "required": False,
            "keys": {
                "auto_detect_host_cli": {"type": bool, "required": False},
            },
        }

    def _collect_declared_secrets(self, context: RunContext) -> list[dict[str, str]]:
        """Collect all secret slots declared for this package (package + feature level)."""
        secrets: list[dict[str, str]] = list(context.get_package_secrets("source-control"))
        for f_sec in context.feature_secrets.get("source-control", {}).values():
            secrets.extend(f_sec)
        return secrets

    def on_run_init(self, context: RunContext) -> None:
        """Resolve real tokens host-side and compute in-container placeholders."""
        cfg = context.get_package_config("source-control")
        if not cfg and self.manifest:
            cfg = dict(self.manifest.config)
        self.sc_cfg = cast("SourceControlConfig", cfg)

        context.add_mode("source-control")
        secrets = self._collect_declared_secrets(context)

        feat_configs_map = context.feature_configs.get("source-control", {})
        tokens = resolve_source_control_tokens(
            secrets=secrets,
            feature_configs=feat_configs_map,
            raw_config=context.config,
            log=logger,
        )
        self.resolved_tokens = tokens
        context.set_attribute("source_control.tokens", tokens)

        # Register real tokens in the trusted host-side registry. The proxy
        # pulls ${ENV:...} references from there; the values never enter the
        # agent container or any CLI argv.
        for var, value in tokens.items():
            register_resolved_secret(var, value)

        # Compute the placeholder-only env block for the agent container.
        self.placeholder_env = resolve_source_control_placeholder_env(secrets, self.manifest)

    def on_preflight(self, context: RunContext) -> None:
        """Reject 'agent.env' overrides of provider token variables.

        Token variables carry placeholders that the proxy substitutes; a
        user-supplied override would place a real (or bogus) credential inside
        the container and break the fail-closed design.
        """
        agent_sec = (context.config or {}).get("agent")
        env = agent_sec.get("env") if isinstance(agent_sec, dict) else None
        if not isinstance(env, dict):
            return
        clashes = sorted(str(k) for k in env if str(k) in GUARDED_TOKEN_ENV_VARS)
        if clashes:
            raise ValueError(
                f"agent.env must not override source-control token variable(s): {', '.join(clashes)}. "
                f"Token values are managed by the source-control package: declare them under "
                f"'packages: source-control: secrets:' with a keyring 'account', and the proxy "
                f"injects them into outgoing requests."
            )

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        context: RunContext,
    ) -> None:
        """Inject placeholder tokens and the setup flag into the container environment.

        Only placeholders are injected — real tokens never reach the agent
        container. The proxy substitutes placeholders in outgoing requests.
        """
        cfg = self.sc_cfg or context.get_package_config("source-control")

        for k, v in self.placeholder_env.items():
            spec.env[k] = v

        # Configure git credential helper behavior
        setup_git = cfg.get("setup_git_credentials", True)
        spec.env["SETUP_GIT_CREDENTIALS"] = "true" if setup_git else "false"
