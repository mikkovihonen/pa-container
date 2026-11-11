from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from packages.plugin import ACPPlugin, ContainerRunSpec, RunContext

from .git import (
    get_sanitized_git_config_json,
    read_git_config,
    resolve_git_hooks_mounts,
    warn_missing_gitignore,
)

if TYPE_CHECKING:
    from pathlib import Path

    from packages.manifest import PackageManifest

    from .types import ProjectGitConfig

logger = get_category_logger(__name__, LogCategory.AGENT)


class GitPlugin(ACPPlugin):
    """ACP Plugin for Git configuration, workspace safety, and repository verification."""

    def __init__(
        self,
        manifest: PackageManifest,
        package_dir: Path,
        project_dir: Path | None = None,
    ) -> None:
        super().__init__(manifest, package_dir, project_dir)
        self.git_cfg: ProjectGitConfig | None = None

    def contribute_config_schema(self) -> dict[str, Any]:
        """Contribute schema dictionary for validating the 'git' section in config.yaml."""
        return {
            "type": dict,
            "keys": {
                "safe_directory": {"type": bool},
                "rewrite_ssh_to_https": {"type": bool},
            },
        }

    def on_run_init(self, context: RunContext) -> None:
        """Register 'git' mode and parse git configuration."""
        pa_dir = (self.project_dir / ".pa-container") if self.project_dir else None
        try:
            cfg = read_git_config(pa_dir)
        except Exception as e:
            logger.debug(f"Could not read git config during init: {e}")
            cfg = {"safe_directory": True, "rewrite_ssh_to_https": True}

        self.git_cfg = cfg
        context.add_mode("git")
        context.set_attribute("git.config", cfg)

    def on_preflight(self, context: RunContext) -> None:
        """Verify git repository safety and warn about missing .gitignore entries."""
        preflight_logger = get_category_logger(__name__, LogCategory.PREFLIGHT)
        warn_missing_gitignore(context.project_dir, preflight_logger)

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        context: RunContext,
    ) -> None:
        """Configure container runtime arguments, environment variables, and git hooks mounts."""
        cfg = self.git_cfg
        if cfg is None:
            pa_dir = (self.project_dir / ".pa-container") if self.project_dir else None
            try:
                cfg = read_git_config(pa_dir)
            except Exception as e:
                logger.debug(f"Could not read git config: {e}")
                cfg = {"safe_directory": True, "rewrite_ssh_to_https": True}
            self.git_cfg = cfg
            context.add_mode("git")
            context.set_attribute("git.config", cfg)

        security_cfg: dict[str, Any] = dict(context.config.get("security") or {})

        # 1. Environment variables
        spec.env["HOST_GIT_CONFIG"] = get_sanitized_git_config_json(
            log=logger,
            allowlist=security_cfg.get("git_config_allowlist"),
        )
        spec.env["GIT_SAFE_DIRECTORY"] = "true" if cfg.get("safe_directory", True) else "false"
        spec.env["GIT_REWRITE_SSH"] = "true" if cfg.get("rewrite_ssh_to_https", True) else "false"

        # 2. Read-only git hooks mounts
        read_only_hooks = bool(security_cfg.get("read_only_git_hooks", True))
        hooks_mounts = resolve_git_hooks_mounts(context.project_dir, read_only_hooks=read_only_hooks)
        spec.extra_run_args.extend(hooks_mounts)

        # 3. Mount entrypoint hooks for container execution
        root_hook = self.package_dir / "container" / "entrypoint.d" / "root" / "20-git.sh"
        if root_hook.is_file():
            spec.extra_run_args.extend(
                ["--volume", f"{root_hook}:/usr/local/share/pa-container/entrypoint.d/root/20-git.sh:ro"]
            )
        agent_hook = self.package_dir / "container" / "entrypoint.d" / "agent" / "20-git.sh"
        if agent_hook.is_file():
            spec.extra_run_args.extend(
                ["--volume", f"{agent_hook}:/usr/local/share/pa-container/entrypoint.d/agent/20-git.sh:ro"]
            )
