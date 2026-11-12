from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

sys.dont_write_bytecode = True

import project
import volumes
from logging_driver import LogCategory, get_category_logger
from packages.plugin import ACPPlugin, ContainerRunSpec, RunContext
from runtimes import get_runtime

if TYPE_CHECKING:
    from config_types import NestedContainersConfig

logger = get_category_logger(__name__, LogCategory.PREFLIGHT)


class PodmanPlugin(ACPPlugin):
    """ACP Plugin for rootless nested container execution (podman)."""

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        context: RunContext,
    ) -> None:
        """Configure runtime arguments and volumes for nested containers."""
        cfg = context.get_package_config("podman")
        if not cfg and self.manifest:
            cfg = dict(self.manifest.config)
        ports_sec = cfg.get("ports") or {}
        nested_cfg = {
            "enabled": True,
            "storage": cfg.get("storage", "volume"),
            "security": cfg.get("security", "disable"),
            "ports": {
                "expose": ports_sec.get("expose", "localhost"),
                "publish": ports_sec.get("publish", []),
            },
        }
        rt = get_runtime()
        proj_dir = self.project_dir or Path.cwd()
        proj_key = project.project_key(proj_dir)

        if nested_cfg["storage"] == "volume":
            orphaned = volumes.cleanup_orphaned_nested_volumes("podman")
            if orphaned:
                logger.info(f"Removed {len(orphaned)} orphaned nested-storage volume(s)")
            vol_name = rt.nested_volume_name(proj_key)
            if not volumes.ensure_nested_volume(
                "podman",
                vol_name,
                project_hash=f"pa-container-{proj_key}",
                project_path=str(proj_dir.resolve()),
            ):
                logger.warning("Falling back to a tmpfs nested image store for this run.")
                nested_cfg = {**nested_cfg, "storage": "tmpfs"}

        nested_cfg_typed = cast("NestedContainersConfig", nested_cfg)
        nested_args = rt.nested_container_args(nested_cfg_typed, proj_key)
        port_args = rt.nested_port_args(nested_cfg_typed)

        logger.info(
            f"Nested containers enabled (storage={nested_cfg['storage']}, security={nested_cfg['security']}): "
            "rootless podman active inside agent container."
        )

        spec.extra_run_args.extend([*nested_args, *port_args])
