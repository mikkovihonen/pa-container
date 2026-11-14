from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from urllib.parse import urlparse

sys.dont_write_bytecode = True

from pa_packages.tunnels.host.tunnel import normalize_tunnel_url

from logging_driver import LogCategory, get_category_logger
from network import resolve_service_port
from packages.plugin import ACPPlugin, ContainerRunSpec, IngressAuthPolicy, RunContext, TunnelEndpointRequest

from .containers import find_running_t3_container
from .t3 import (
    synthesize_t3_policy,
    synthesize_t3_settings,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from packages.manifest import PackageManifest

logger = get_category_logger(__name__, LogCategory.NETWORK)


class AgentOrchestratorsPlugin(ACPPlugin):
    """ACP Plugin for Agent Orchestrators capability and T3 Code web interface orchestration."""

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

    def register_cli_args(self, run_parser: argparse.ArgumentParser) -> None:
        """Register CLI argument flags contributed by T3."""
        grp = run_parser.add_argument_group("T3 Code Options")
        grp.add_argument(
            "--t3",
            action="store_true",
            help="Enable T3 Code web server mode inside the agent container.",
        )
        grp.add_argument(
            "--t3-lan",
            action="store_true",
            help="Allow T3 Code inbound connections from LAN devices (binds 0.0.0.0).",
        )
        grp.add_argument(
            "--t3-port",
            help="Port for T3 Code web server (integer or 'auto'). Defaults to 3773 or next available port if in use.",
        )
        grp.add_argument(
            "--t3-advertise-host",
            help="Hostname or IP address to advertise for T3 pairing (e.g. 'external' or IP).",
        )
        grp.add_argument(
            "--t3-public-url",
            help="Pre-existing public HTTPS URL override for T3 pairing link.",
        )

    def on_run_init(self, context: RunContext) -> None:
        """Inspect options and config to activate T3 mode in RunContext."""
        options = context.options
        config = context.config
        cli_t3 = bool(options.get("t3", False))
        cli_port = options.get("t3_port")
        cli_public_url = options.get("t3_public_url")
        cli_advertise_host = options.get("t3_advertise_host")
        cli_lan = bool(options.get("t3_lan", False))

        agent_cfg = config.get("agent")
        agent_mode = agent_cfg.get("mode") if isinstance(agent_cfg, dict) else None
        raw_cfg: dict[str, object] = dict(config)
        raw_t3 = raw_cfg.get("t3")
        t3_enabled = bool(raw_t3.get("enabled", False)) if isinstance(raw_t3, dict) else False

        is_requested = any(
            [
                cli_t3,
                cli_port,
                cli_public_url,
                cli_advertise_host,
                cli_lan,
                agent_mode == "t3",
                t3_enabled,
            ]
        )

        if is_requested:
            context.add_mode("t3")
            context.add_mode("multi-agent")
            context.set_attribute("orchestrator", "t3")

    def on_preflight(self, context: RunContext) -> None:
        """Validate single-container lock for T3 workspace."""
        if not context.has_mode("t3") or not self.project_dir:
            return

        # Exclusive workspace lock
        running_t3 = find_running_t3_container(self.project_dir, runtime=context.runtime)
        if running_t3:
            pid_info = f" (launcher pid {running_t3.launcher_pid})" if running_t3.launcher_pid else ""
            raise RuntimeError(
                f"A T3 mode pa-container is already running for this workspace: {running_t3.container_name}{pid_info}\n"
                f"Only one T3 mode container can run per workspace at a time because T3 Code requires "
                f"exclusive ownership of the workspace's T3 state.\n\n"
                f"To stop the existing container, run:\n"
                f"  {context.runtime} stop {running_t3.container_name}\n\n"
                f"Or attach to the existing T3 session in the terminal where it was started."
            )

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        context: RunContext,
    ) -> None:
        """Synthesize T3 settings, policy, and container run arguments."""
        if not context.has_mode("t3") or not self.project_dir:
            return

        options = context.options
        from pa_packages.agents.host.registry import get_agent_driver

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

        cli_lan = bool(options.get("t3_lan", False))
        host_bind = "0.0.0.0" if cli_lan else "127.0.0.1"
        self.t3_port = resolve_service_port(
            requested_port=options.get("t3_port"),
            default_port=3773,
            host=host_bind,
            fallback_to_ephemeral=True,
            service_name="T3 Code",
        )

        cli_adv_host = options.get("t3_advertise_host")
        self.t3_advertise_host = str(cli_adv_host or "localhost")
        self.t3_public_url = options.get("t3_public_url")

        # Register T3 service with generic tunnel provider if active
        if context.tunnel_provider and context.tunnel_provider.is_enabled():
            endpoint = context.tunnel_provider.register_service(
                TunnelEndpointRequest(
                    service_name="t3",
                    port=self.t3_port,
                    protocol="http",
                    auth_policy=IngressAuthPolicy.INTRINSIC,
                    preferred_subdomain="t3",
                    title="T3 Code Web UI",
                )
            )
            if endpoint:
                self.t3_public_url = self.t3_public_url or endpoint.public_url
                if not cli_adv_host:
                    self.t3_advertise_host = endpoint.advertised_host

        if self.t3_public_url:
            self.t3_public_url = normalize_tunnel_url(self.t3_public_url)
            if not cli_adv_host and not (context.tunnel_provider and context.tunnel_provider.is_enabled()):
                self.t3_advertise_host = urlparse(self.t3_public_url).hostname or self.t3_advertise_host

        spec.ports.append(f"{host_bind}:{self.t3_port}:{self.t3_port}")
        spec.chown_paths.append("/home/agent/.t3")

        args: list[str] = [
            "--volume",
            f"{self.t3_dir}:/home/agent/.t3",
            "--volume",
            f"{self.t3_dir / 'policy.json'}:/etc/t3code/policy.json:ro",
            "--label",
            "pa-container.mode=t3",
        ]

        shim_src = self.package_dir / "container" / "bin" / "t3-advertise-host.cjs"
        if shim_src.is_file():
            args.extend(["--volume", f"{shim_src}:/usr/local/share/pa-container/t3-advertise-host.cjs:ro"])
        sync_src = self.package_dir / "container" / "bin" / "t3-sync-antigravity.py"
        if sync_src.is_file():
            args.extend(["--volume", f"{sync_src}:/usr/local/share/pa-container/t3-sync-antigravity.py:ro"])
        mode_src = self.package_dir / "container" / "modes" / "t3.sh"
        if mode_src.is_file():
            args.extend(["--volume", f"{mode_src}:/usr/local/share/pa-container/modes/t3.sh:ro"])

        env: dict[str, str] = {
            "PA_CONTAINER_MODE": "t3",
            "T3_PORT": str(self.t3_port),
            "T3_ADVERTISE_HOST": self.t3_advertise_host,
        }
        if cli_lan:
            env["T3_LAN"] = "true"
        if self.t3_public_url:
            env["T3_PUBLIC_URL"] = self.t3_public_url

        spec.extra_run_args.extend(args)
        spec.env.update(env)

    def post_start(self, context: RunContext) -> None:
        """Render T3 Code connection and pairing notifications."""
        if not context.has_mode("t3"):
            return

        from logging_driver import LogDriver

        log_drv = LogDriver(context.project_dir)
        if not log_drv.quiet:
            log_drv.console.print(
                f"\n  [bold green]T3 Code mode enabled (https://t3.codes):[/bold green]\n"
                f"  Port: {self.t3_port} | Advertise host: {self.t3_advertise_host}\n"
                f"  Once initialized, open https://t3.codes and use the pairing link displayed below."
            )


T3Plugin = AgentOrchestratorsPlugin
