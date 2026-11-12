from __future__ import annotations

import sys
import threading
import webbrowser
from typing import TYPE_CHECKING, Any, cast

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from packages.plugin import ACPPlugin, ContainerRunSpec, RunContext

from .desktop import (
    resolve_desktop_ports,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from packages.manifest import PackageManifest

    from .types import DesktopConfig

logger = get_category_logger(__name__, LogCategory.DESKTOP)

DESKTOP_BACKENDS = ("wayland", "x11")
DEFAULT_BACKEND = "wayland"


class VirtualDesktopPlugin(ACPPlugin):
    """ACP Plugin for virtual headless desktop support (wayland/x11 backends with noVNC streaming)."""

    def __init__(
        self,
        manifest: PackageManifest,
        package_dir: Path,
        project_dir: Path | None = None,
    ) -> None:
        super().__init__(manifest, package_dir, project_dir)
        self.desktop_cfg: DesktopConfig | None = None
        self.backend: str | None = None
        self.novnc_port: int | None = None
        self.vnc_port: int | None = None
        self.novnc_url: str | None = None
        self.vnc_endpoint: str | None = None

    def register_cli_commands(
        self,
        subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
        common_parser: argparse.ArgumentParser | None = None,
    ) -> None:
        """Register the 'desktop' subcommand contributed by this package."""
        from .desktop import handle_desktop_command

        parents = [common_parser] if common_parser is not None else []
        desktop_parser = subparsers.add_parser(
            "desktop",
            parents=parents,
            help="Inspect active virtual desktop containers, noVNC web UIs, and VNC endpoints.",
            description="Query active virtual desktop sessions for this project or globally, showing clickable links and status.",
        )
        desktop_parser.add_argument(
            "--all",
            action="store_true",
            help="List all active virtual desktop containers across all projects.",
        )
        desktop_parser.add_argument(
            "--open",
            action="store_true",
            help="Open the noVNC web UI in the default OS web browser.",
        )
        desktop_parser.add_argument(
            "--url",
            action="store_true",
            help="Print only the noVNC web UI URL (for shell scripts or piping).",
        )
        desktop_parser.add_argument(
            "--vnc",
            action="store_true",
            help="Print only the VNC endpoint host:port (for VNC clients).",
        )
        desktop_parser.add_argument(
            "--json",
            action="store_true",
            help="Output virtual desktop metadata in JSON format.",
        )
        desktop_parser.set_defaults(_acp_handler=handle_desktop_command)

    def contribute_config_schema(self) -> dict[str, Any]:
        """Contribute schema dictionary for validating the desktop configuration section."""
        return {
            "type": dict,
            "keys": {
                "enabled": {"type": bool, "required": False},
                "resolution": {"type": str},
                "compositor": {"type": str},
                "open_browser": {"type": bool},
                "vnc": {
                    "type": dict,
                    "keys": {
                        "enabled": {"type": bool},
                        "port": {"type": (int, str)},
                        "expose": {"type": str},
                    },
                },
                "novnc": {
                    "type": dict,
                    "keys": {
                        "enabled": {"type": bool},
                        "port": {"type": (int, str)},
                        "expose": {"type": str},
                    },
                },
                "gpu": {
                    "type": dict,
                    "keys": {
                        "enabled": {"type": (bool, str)},
                    },
                },
            },
        }

    def _active_desktop_features(self, context: RunContext) -> set[str]:
        """Resolve the virtual-desktop features enabled in the project configuration."""
        feats: set[str] = set()
        try:
            from images import resolve_project_packages

            specs = resolve_project_packages(context.project_dir)
            feats = {str(f) for f in (specs.get("virtual-desktop") or [])}
        except Exception as e:
            logger.debug(f"Could not resolve virtual-desktop features from project config: {e}")
        if not feats and self.manifest is not None:
            feats = {name for name, f in self.manifest.features.items() if f.default}
        return feats

    def _resolve_backend(self, context: RunContext) -> str:
        """Resolve the active display backend (wayland or x11) from the project configuration."""
        feats = self._active_desktop_features(context)
        if not feats:
            return DEFAULT_BACKEND

        unknown = sorted(feats - set(DESKTOP_BACKENDS))
        if unknown:
            raise ValueError(
                f"virtual-desktop: unknown display backend feature(s): {', '.join(unknown)}. "
                f"Available backends: {', '.join(DESKTOP_BACKENDS)}."
            )
        if len(feats) > 1:
            raise ValueError(
                "virtual-desktop: display backends are mutually exclusive; enable exactly one of "
                f"{', '.join(DESKTOP_BACKENDS)} under 'features' for the virtual-desktop package."
            )
        return next(iter(feats))

    def on_run_init(self, context: RunContext) -> None:
        """Register desktop mode, configuration, and active display backend in the run context."""
        raw_cfg = context.get_package_config("virtual-desktop")
        if not raw_cfg and self.manifest:
            raw_cfg = dict(self.manifest.config)

        cfg: DesktopConfig = cast("DesktopConfig", raw_cfg or {})
        self.desktop_cfg = cfg
        context.add_mode("desktop")
        context.set_attribute("desktop.config", cfg)

        self.backend = self._resolve_backend(context)
        context.set_attribute("desktop.backend", self.backend)

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        context: RunContext,
    ) -> None:
        """Configure container run arguments for virtual desktop and GPU passthrough."""
        cfg = self.desktop_cfg
        if cfg is None:
            raw_cfg = context.get_package_config("virtual-desktop")
            if not raw_cfg and self.manifest:
                raw_cfg = dict(self.manifest.config)
            cfg = cast("DesktopConfig", raw_cfg or {})
            self.desktop_cfg = cfg
            context.add_mode("desktop")
            context.set_attribute("desktop.config", cfg)

        backend = self.backend or self._resolve_backend(context)
        self.backend = backend

        self.novnc_port, self.vnc_port = resolve_desktop_ports(cfg)
        self.novnc_url = f"http://127.0.0.1:{self.novnc_port}/vnc.html?autoconnect=true&resize=scale"
        self.vnc_endpoint = f"127.0.0.1:{self.vnc_port}"

        context.set_attribute("desktop.backend", backend)
        context.set_attribute("desktop.novnc_port", self.novnc_port)
        context.set_attribute("desktop.vnc_port", self.vnc_port)
        context.set_attribute("desktop.novnc_url", self.novnc_url)
        context.set_attribute("desktop.vnc_endpoint", self.vnc_endpoint)

        novnc_cfg = cfg.get("novnc") or {}
        vnc_cfg = cfg.get("vnc") or {}
        novnc_bind = "" if novnc_cfg.get("expose") == "lan" else "127.0.0.1:"
        vnc_bind = "" if vnc_cfg.get("expose") == "lan" else "127.0.0.1:"
        resolution = cfg.get("resolution", "1920x1080")

        spec.ports.append(f"{novnc_bind}{self.novnc_port}:6080")
        spec.ports.append(f"{vnc_bind}{self.vnc_port}:5900")

        desktop_env = {
            "PA_CONTAINER_DESKTOP": "true",
            "PA_DESKTOP_BACKEND": backend,
            "PA_DESKTOP_RESOLUTION": resolution,
            "DISPLAY": ":0",
            "XDG_RUNTIME_DIR": "/run/user/1000",
        }
        if backend == "wayland":
            desktop_env["WAYLAND_DISPLAY"] = "wayland-0"
        spec.env.update(desktop_env)

        gpu_cfg = cfg.get("gpu") or {}
        gpu_mode = gpu_cfg.get("enabled", "auto")
        if gpu_mode is not False and str(gpu_mode).lower() not in ("false", "0", "off", "no"):
            from pathlib import Path

            if Path("/dev/dri").exists():
                spec.devices.append("/dev/dri")
                spec.extra_run_args.extend(["--group-add", "keep-groups"])
            elif gpu_mode is True or str(gpu_mode).lower() in ("true", "1", "yes", "on"):
                logger.warning(
                    "/dev/dri requested by config but does not exist on host; falling back to software rasterizer."
                )

        spec.extra_run_args.extend(
            [
                "--label",
                "pa-container.desktop.enabled=true",
                "--label",
                f"pa-container.desktop.backend={backend}",
            ]
        )

        root_hook = self.package_dir / "container" / "entrypoint.d" / "root" / "60-desktop.sh"
        if root_hook.is_file():
            spec.extra_run_args.extend(
                ["--volume", f"{root_hook}:/usr/local/share/pa-container/entrypoint.d/root/60-desktop.sh:ro"]
            )
        agent_hook = self.package_dir / "container" / "entrypoint.d" / "agent" / "60-desktop.sh"
        if agent_hook.is_file():
            spec.extra_run_args.extend(
                ["--volume", f"{agent_hook}:/usr/local/share/pa-container/entrypoint.d/agent/60-desktop.sh:ro"]
            )

        for hook_kind in ("root", "agent"):
            backend_hook = self.package_dir / "features" / backend / "entrypoint.d" / hook_kind / "61-desktop.sh"
            if backend_hook.is_file():
                spec.extra_run_args.extend(
                    [
                        "--volume",
                        f"{backend_hook}:/usr/local/share/pa-container/entrypoint.d/{hook_kind}/61-desktop.sh:ro",
                    ]
                )

        backend_desc = "labwc + wayvnc" if backend == "wayland" else "Xvfb + openbox + x11vnc"
        logger.info(
            f"Virtual Desktop enabled ({backend} backend: {backend_desc}, "
            f"{cfg.get('resolution', '1920x1080')}):\n"
            f"  noVNC Web UI: {self.novnc_url}\n"
            f"  VNC Endpoint: {self.vnc_endpoint}"
        )

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
