from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

sys.dont_write_bytecode = True

import project
import volumes
from logging_driver import LogCategory, get_category_logger
from network import read_nested_containers_config
from packages.plugin import ACPPlugin, ContainerRunSpec
from runtimes import get_runtime

if TYPE_CHECKING:
    from cli import RunOptions
    from config_types import ProjectConfig

logger = get_category_logger(__name__, LogCategory.PREFLIGHT)


class PodmanPlugin(ACPPlugin):
    """ACP Plugin for rootless nested container execution (podman)."""

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        config: ProjectConfig,
        options: RunOptions,
    ) -> None:
        """Configure runtime arguments and volumes for nested containers."""
        pa_dir = (self.project_dir / ".pa-container") if self.project_dir else None
        try:
            nested_cfg = read_nested_containers_config(pa_dir)
        except Exception as e:
            logger.debug(f"Could not read nested container config: {e}")
            nested_cfg = {
                "enabled": True,
                "storage": "volume",
                "security": "confined",
                "ports": {"publish": [], "expose": "localhost"},
            }

        nested_cfg["enabled"] = True
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

        nested_args = rt.nested_container_args(nested_cfg, proj_key)
        port_args = rt.nested_port_args(nested_cfg)

        logger.info(
            f"Nested containers enabled (storage={nested_cfg['storage']}, security={nested_cfg['security']}): "
            "rootless podman active inside agent container."
        )

        spec.extra_run_args.extend([*nested_args, *port_args])
