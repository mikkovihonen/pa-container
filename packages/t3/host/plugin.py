from __future__ import annotations

import sys
from typing import TYPE_CHECKING

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from packages.plugin import ACPPlugin, ContainerRunSpec, RunContext

from .t3 import (
    synthesize_t3_policy,
    synthesize_t3_settings,
)

if TYPE_CHECKING:
    from pathlib import Path

    from cli import RunOptions
    from config_types import ProjectConfig
    from packages.manifest import PackageManifest

logger = get_category_logger(__name__, LogCategory.NETWORK)


class T3Plugin(ACPPlugin):
    """ACP Plugin for T3 Code web interface orchestration."""

    def __init__(
        self,
        manifest: PackageManifest,
        package_dir: Path,
        project_dir: Path | None = None,
    ) -> None:
        super().__init__(manifest, package_dir, project_dir)
        self.t3_dir: Path | None = None
        self.t3_port: int = 3773
        self.t3_advertise_host: str = "localhost"
        self.t3_public_url: str | None = None

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        config: ProjectConfig,
        options: RunOptions,
    ) -> None:
        """Synthesize T3 settings, policy, and container run arguments."""
        is_t3 = bool(
            getattr(options, "t3", False)
            or config.get("agent", {}).get("mode") == "t3"
            or (self.manifest and "t3" in self.manifest.name)
        )
        if not is_t3 or not self.project_dir:
            return

        from agents import get_agent_driver
        from network import read_default_agent, read_enabled_agents

        pa_dir = self.project_dir / ".pa-container"
        self.t3_dir = pa_dir / "t3"
        self.t3_dir.mkdir(parents=True, exist_ok=True)

        try:
            active_name = read_default_agent(pa_dir)
            active_driver = get_agent_driver(active_name)
            enabled_names = read_enabled_agents(pa_dir)
            enabled_drivers = [get_agent_driver(n) for n in enabled_names]
        except Exception as e:
            logger.debug(f"Could not resolve agent drivers for T3: {e}")
            return

        synthesize_t3_settings(self.t3_dir, active_driver, enabled_drivers, project_dir=self.project_dir)
        synthesize_t3_policy(self.t3_dir, enabled_drivers)

        self.t3_port = int(getattr(options, "t3_port", None) or 3773)
        self.t3_advertise_host = str(getattr(options, "t3_advertise_host", None) or "localhost")
        self.t3_public_url = getattr(options, "t3_public_url", None)

        args: list[str] = [
            "--volume",
            f"{self.t3_dir}:/home/agent/.t3",
            "--volume",
            f"{self.t3_dir / 'policy.json'}:/etc/t3code/policy.json:ro",
            "--label",
            "pa-container.mode=t3",
        ]

        # In dev or unbuilt package environments, volume mount scripts if present
        shim_src = self.package_dir / "container" / "bin" / "t3-advertise-host.cjs"
        if shim_src.is_file():
            args.extend(["--volume", f"{shim_src}:/usr/local/share/pa-container/t3-advertise-host.cjs:ro"])
        sync_src = self.package_dir / "container" / "bin" / "t3-sync-antigravity.py"
        if sync_src.is_file():
            args.extend(["--volume", f"{sync_src}:/usr/local/share/pa-container/t3-sync-antigravity.py:ro"])

        env: dict[str, str] = {
            "PA_CONTAINER_MODE": "t3",
            "T3_PORT": str(self.t3_port),
            "T3_ADVERTISE_HOST": self.t3_advertise_host,
        }
        if self.t3_public_url:
            env["T3_PUBLIC_URL"] = self.t3_public_url

        spec.extra_run_args.extend(args)
        spec.env.update(env)

    def post_start(self, ctx: RunContext) -> None:
        """Render T3 Code connection and tunnel notifications."""
        if not self.t3_dir:
            return

        from logging_driver import LogDriver

        log_drv = LogDriver(ctx.project_dir)
        if not log_drv.quiet and self.t3_public_url:
            log_drv.console.print(
                f"  [dim cyan][{LogCategory.NETWORK}][/dim cyan] T3 Tunnel URL: "
                f"[link={self.t3_public_url}]{self.t3_public_url}[/link] 🔗 (click to open)"
            )
