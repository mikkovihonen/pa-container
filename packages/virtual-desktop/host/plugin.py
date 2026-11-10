from __future__ import annotations

import sys
import threading
import webbrowser
from typing import TYPE_CHECKING

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from packages.plugin import ACPPlugin, ContainerRunSpec, RunContext
from runtimes import get_runtime

from .desktop import (
    read_desktop_config,
    resolve_desktop_ports,
)

if TYPE_CHECKING:
    from pathlib import Path

    from cli import RunOptions
    from config_types import DesktopConfig, ProjectConfig
    from packages.manifest import PackageManifest

logger = get_category_logger(__name__, LogCategory.DESKTOP)


class VirtualDesktopPlugin(ACPPlugin):
    """ACP Plugin for virtual headless Wayland/noVNC desktop support."""

    def __init__(
        self,
        manifest: PackageManifest,
        package_dir: Path,
        project_dir: Path | None = None,
    ) -> None:
        super().__init__(manifest, package_dir, project_dir)
        self.desktop_cfg: DesktopConfig | None = None
        self.novnc_port: int | None = None
        self.vnc_port: int | None = None
        self.novnc_url: str | None = None
        self.vnc_endpoint: str | None = None

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        config: ProjectConfig,
        options: RunOptions,
    ) -> None:
        """Configure container run arguments for virtual desktop and GPU passthrough."""
        pa_dir = (self.project_dir / ".pa-container") if self.project_dir else None
        try:
            cfg = read_desktop_config(pa_dir)
        except Exception as e:
            logger.debug(f"Could not read desktop config: {e}")
            return

        if not cfg.get("enabled"):
            return

        self.desktop_cfg = cfg
        self.novnc_port, self.vnc_port = resolve_desktop_ports(cfg)
        self.novnc_url = f"http://127.0.0.1:{self.novnc_port}/vnc.html?autoconnect=true&resize=scale"
        self.vnc_endpoint = f"127.0.0.1:{self.vnc_port}"

        rt = get_runtime()
        desktop_args = rt.desktop_run_args(
            cfg,
            novnc_port=self.novnc_port,
            vnc_port=self.vnc_port,
        )
        gpu_args = rt.opportunistic_gpu_args(cfg.get("gpu"))

        all_args: list[str] = [
            *desktop_args,
            *gpu_args,
            "--label",
            "pa-container.desktop.enabled=true",
        ]

        logger.info(
            f"Virtual Desktop enabled ({cfg['resolution']}, {cfg['compositor']}):\n"
            f"  noVNC Web UI: {self.novnc_url}\n"
            f"  VNC Endpoint: {self.vnc_endpoint}"
        )

        spec.extra_run_args.extend(all_args)

    def post_start(self, ctx: RunContext) -> None:
        """Render desktop URL notifications and optionally open browser."""
        if not self.desktop_cfg or not self.desktop_cfg.get("enabled") or not self.novnc_url:
            return

        from logging_driver import LogDriver

        log_drv = LogDriver(ctx.project_dir)
        if not log_drv.quiet:
            log_drv.console.print(
                f"  [dim cyan][{LogCategory.DESKTOP}][/dim cyan] Virtual Desktop: "
                f"[link={self.novnc_url}]{self.novnc_url}[/link] "
                f"[dim](VNC: {self.vnc_endpoint}) 🔗 (click to open)[/dim]"
            )

        eff_open = getattr(ctx.options, "open_browser", None)
        if eff_open is None:
            eff_open = self.desktop_cfg.get("open_browser", False)

        if eff_open:
            url = self.novnc_url

            def _open() -> None:
                logger.info(f"Launching virtual desktop UI in default web browser: {url}")
                webbrowser.open(url)

            threading.Thread(target=_open, daemon=True).start()
