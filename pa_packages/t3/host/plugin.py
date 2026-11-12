from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from urllib.parse import urlparse

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from network import resolve_service_port
from packages.plugin import ACPPlugin, ContainerRunSpec, RunContext

from .containers import find_running_t3_container
from .t3 import (
    synthesize_t3_policy,
    synthesize_t3_settings,
)
from .tunnel import (
    CloudflareTunnelManager,
    TailscaleTunnelManager,
    normalize_tunnel_url,
    validate_tunnel_prerequisites,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

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
            "--t3-tunnel",
            choices=["tailscale", "cloudflare"],
            help="Automated secure tunnel provider for remote T3 pairing.",
        )
        grp.add_argument(
            "--t3-tunnel-domain",
            help="Custom public hostname for Cloudflare tunnel.",
        )
        grp.add_argument(
            "--t3-tunnel-quick",
            action="store_true",
            help="Use a quick ephemeral trycloudflare tunnel without pre-created credentials.",
        )
        grp.add_argument(
            "--t3-tunnel-runner",
            choices=["auto", "container", "host"],
            default=None,
            help="Runner environment for cloudflared tunnel daemon.",
        )
        grp.add_argument(
            "--t3-tunnel-keyring-account",
            default=None,
            help="OS keyring credential account holding the Cloudflare tunnel token.",
        )
        grp.add_argument(
            "--t3-tunnel-tailscale-mode",
            choices=["serve", "funnel"],
            default=None,
            help="Tailscale exposure mode: 'serve' (tailnet-only) or 'funnel' (public internet).",
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
        cli_tunnel = options.get("t3_tunnel")
        cli_port = options.get("t3_port")
        cli_public_url = options.get("t3_public_url")
        cli_advertise_host = options.get("t3_advertise_host")
        cli_lan = bool(options.get("t3_lan", False))
        cli_quick = bool(options.get("t3_tunnel_quick", False))
        cli_domain = options.get("t3_tunnel_domain")
        cli_runner = options.get("t3_tunnel_runner")
        cli_keyring = options.get("t3_tunnel_keyring_account")
        cli_ts_mode = options.get("t3_tunnel_tailscale_mode")

        agent_cfg = config.get("agent")
        agent_mode = agent_cfg.get("mode") if isinstance(agent_cfg, dict) else None
        raw_cfg: dict[str, object] = dict(config)
        raw_t3 = raw_cfg.get("t3")
        t3_enabled = bool(raw_t3.get("enabled", False)) if isinstance(raw_t3, dict) else False

        is_requested = any(
            [
                cli_t3,
                cli_tunnel,
                cli_port,
                cli_public_url,
                cli_advertise_host,
                cli_lan,
                cli_quick,
                cli_domain,
                cli_runner,
                cli_keyring,
                cli_ts_mode,
                agent_mode == "t3",
                t3_enabled,
            ]
        )

        if is_requested:
            context.add_mode("t3")
            context.add_mode("multi-agent")
            context.set_attribute("orchestrator", "t3")

    def on_preflight(self, context: RunContext) -> None:
        """Validate single-container lock and tunnel prerequisites."""
        if not context.has_mode("t3") or not self.project_dir:
            return

        # 1. Exclusive workspace lock
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

        # 2. Tunnel prerequisites validation
        options = context.options
        tunnel_type = options.get("t3_tunnel")
        quick = bool(options.get("t3_tunnel_quick", False))
        domain = options.get("t3_tunnel_domain")
        runner = options.get("t3_tunnel_runner")
        keyring_account = options.get("t3_tunnel_keyring_account")
        tailscale_mode = options.get("t3_tunnel_tailscale_mode")

        if not tunnel_type:
            has_cf = bool(quick or domain or runner or keyring_account)
            has_ts = bool(tailscale_mode)
            if has_cf and not has_ts:
                tunnel_type = "cloudflare"
            elif has_ts and not has_cf:
                tunnel_type = "tailscale"

        if tunnel_type or quick or domain or runner or keyring_account or tailscale_mode:
            validate_tunnel_prerequisites(
                tunnel_type=tunnel_type,
                domain=domain,
                quick=quick,
                runner=runner,
                keyring_account=keyring_account,
                tailscale_mode=tailscale_mode,
                runtime=context.runtime,
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

        # Start tunnel if requested and ExitStack is provided
        cli_tunnel = options.get("t3_tunnel")
        quick = bool(options.get("t3_tunnel_quick", False))
        domain = options.get("t3_tunnel_domain")
        runner = options.get("t3_tunnel_runner")
        keyring_account = options.get("t3_tunnel_keyring_account")
        tailscale_mode = options.get("t3_tunnel_tailscale_mode")

        if not cli_tunnel:
            has_cf = bool(quick or domain or runner or keyring_account)
            has_ts = bool(tailscale_mode)
            if has_cf and not has_ts:
                cli_tunnel = "cloudflare"
            elif has_ts and not has_cf:
                cli_tunnel = "tailscale"

        if cli_tunnel and context.exit_stack:
            ttype = cli_tunnel.strip().lower()
            if ttype == "tailscale":
                ts_mgr = TailscaleTunnelManager(mode=tailscale_mode, port=self.t3_port)
                pub_url, adv_host = ts_mgr.start(context.exit_stack)
                self.t3_public_url = self.t3_public_url or pub_url
                if not cli_adv_host:
                    self.t3_advertise_host = adv_host
            elif ttype == "cloudflare":
                cf_mgr = CloudflareTunnelManager(
                    domain=domain,
                    quick=quick,
                    runner=runner,
                    keyring_account=keyring_account,
                    port=self.t3_port,
                    runtime=context.runtime,
                )
                pub_url, adv_host = cf_mgr.start(context.exit_stack)
                self.t3_public_url = self.t3_public_url or pub_url
                if not cli_adv_host:
                    self.t3_advertise_host = adv_host

        if self.t3_public_url:
            self.t3_public_url = normalize_tunnel_url(self.t3_public_url)
            if not cli_adv_host and not cli_tunnel:
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
        """Render T3 Code connection and tunnel notifications."""
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
            if self.t3_public_url:
                log_drv.console.print(
                    f"  [dim cyan][{LogCategory.NETWORK}][/dim cyan] T3 Tunnel URL: "
                    f"[link={self.t3_public_url}]{self.t3_public_url}[/link] 🔗 (click to open)"
                )
