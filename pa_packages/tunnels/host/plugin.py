from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from packages.plugin import ACPPlugin, ContainerRunSpec, RunContext

from .auth_gate import (
    validate_basic_auth_credentials,
    validate_oidc_config,
)
from .tunnel import (
    TunnelService,
    validate_tunnel_prerequisites,
)

if TYPE_CHECKING:
    import argparse
    from pathlib import Path

    from packages.manifest import PackageManifest

logger = get_category_logger(__name__, LogCategory.NETWORK)


class TunnelsPlugin(ACPPlugin):
    """ACP Plugin for generic secure ingress tunneling (Cloudflare and Tailscale)."""

    def __init__(
        self,
        manifest: PackageManifest,
        package_dir: Path,
        project_dir: Path | None = None,
    ) -> None:
        super().__init__(manifest, package_dir, project_dir)
        self.service: TunnelService | None = None

    def register_cli_args(self, run_parser: argparse.ArgumentParser) -> None:
        """Register canonical tunnel CLI arguments."""
        grp = run_parser.add_argument_group("Ingress & Secure Tunnel Options")
        grp.add_argument(
            "--tunnel",
            choices=["tailscale", "cloudflare"],
            help="Automated secure tunnel provider for remote ingress.",
        )
        grp.add_argument(
            "--tunnel-domain",
            help="Custom public domain/hostname on Cloudflare.",
        )
        grp.add_argument(
            "--tunnel-quick",
            action="store_true",
            help="Use ephemeral trycloudflare.com tunnel without pre-created credentials.",
        )
        grp.add_argument(
            "--tunnel-runner",
            choices=["auto", "container", "host"],
            default=None,
            help="Runner environment for cloudflared tunnel daemon (default: 'auto').",
        )
        grp.add_argument(
            "--tunnel-keyring-account",
            default=None,
            help="OS keyring credential account holding the Cloudflare tunnel token.",
        )
        grp.add_argument(
            "--tunnel-tailscale-mode",
            choices=["serve", "funnel"],
            default=None,
            help="Tailscale exposure mode: 'serve' (tailnet-only) or 'funnel' (public internet).",
        )
        grp.add_argument(
            "--tunnel-auth",
            choices=["auto", "oidc", "basic", "token", "none"],
            default=None,
            help="Ingress authentication gate mode for unauthenticated services (default: 'auto').",
        )
        grp.add_argument(
            "--tunnel-oidc-provider",
            help="Identity provider for OIDC auth gate (e.g. 'google', 'github', 'azure', 'keycloak').",
        )
        grp.add_argument(
            "--tunnel-oidc-email-domain",
            help="Allowed email domain for corporate SSO (e.g. 'company.com').",
        )
        grp.add_argument(
            "--tunnel-basic-user",
            help="Explicit username for HTTP Basic Auth.",
        )
        grp.add_argument(
            "--tunnel-basic-keyring-account",
            help="OS keyring account holding the explicit Basic Auth password.",
        )
        grp.add_argument(
            "--tunnel-services",
            help="Comma-separated list of services to expose (default: all registered services).",
        )
        grp.add_argument(
            "--tunnel-allow-insecure",
            action="store_true",
            help="Explicitly permit public unauthenticated exposure of sensitive services without an auth gate.",
        )

    def contribute_config_schema(self) -> dict[str, Any]:
        """Contribute schema dictionary for validating the tunnels configuration section."""
        return {
            "type": dict,
            "keys": {
                "provider": {"type": str, "required": False},
                "domain": {"type": str, "required": False},
                "quick": {"type": bool, "required": False},
                "runner": {"type": str, "required": False},
                "keyring_account": {"type": str, "required": False},
                "tailscale_mode": {"type": str, "required": False},
                "services": {"type": list, "required": False},
                "allow_insecure": {"type": bool, "required": False},
                "auth": {
                    "type": dict,
                    "required": False,
                    "keys": {
                        "type": {"type": str, "required": False},
                        "oidc": {"type": dict, "required": False},
                        "basic": {
                            "type": dict,
                            "required": False,
                            "keys": {
                                "username": {"type": str, "required": True},
                                "password_keyring_account": {"type": str, "required": True},
                            },
                        },
                    },
                },
            },
        }

    def on_run_init(self, context: RunContext) -> None:
        """Inspect options and config to initialize TunnelService on RunContext."""
        options = context.options
        pkg_cfg = context.get_package_config("tunnels")

        # 1. Resolve Provider
        cli_tunnel = options.get("tunnel")
        cfg_provider = pkg_cfg.get("provider") if isinstance(pkg_cfg, dict) else None
        cli_quick = bool(options.get("tunnel_quick", False))
        cfg_quick = bool(pkg_cfg.get("quick", False)) if isinstance(pkg_cfg, dict) else False
        quick = cli_quick or cfg_quick

        cli_domain = options.get("tunnel_domain")
        cfg_domain = pkg_cfg.get("domain") if isinstance(pkg_cfg, dict) else None
        domain = cli_domain or cfg_domain

        provider = cli_tunnel or cfg_provider
        if not provider:
            if quick or domain:
                provider = "cloudflare"
            elif options.get("tunnel_tailscale_mode") or (isinstance(pkg_cfg, dict) and pkg_cfg.get("tailscale_mode")):
                provider = "tailscale"

        if not provider:
            return

        # 2. Resolve Parameters
        runner = (
            options.get("tunnel_runner") or (pkg_cfg.get("runner") if isinstance(pkg_cfg, dict) else None) or "auto"
        )
        keyring_account = (
            options.get("tunnel_keyring_account")
            or (pkg_cfg.get("keyring_account") if isinstance(pkg_cfg, dict) else None)
            or "CLOUDFLARE_TUNNEL_TOKEN"
        )
        tailscale_mode = (
            options.get("tunnel_tailscale_mode")
            or (pkg_cfg.get("tailscale_mode") if isinstance(pkg_cfg, dict) else None)
            or "serve"
        )
        allow_insecure = bool(options.get("tunnel_allow_insecure", False)) or bool(
            pkg_cfg.get("allow_insecure", False) if isinstance(pkg_cfg, dict) else False
        )

        cli_services = options.get("tunnel_services")
        selected_services: list[str] | None = None
        if cli_services:
            selected_services = [s.strip().lower() for s in str(cli_services).split(",") if s.strip()]
        elif isinstance(pkg_cfg, dict) and isinstance(pkg_cfg.get("services"), list):
            selected_services = [str(s).strip().lower() for s in pkg_cfg["services"] if str(s).strip()]

        # 3. Resolve Auth Configuration
        auth_sec: dict[str, Any] = {}
        if isinstance(pkg_cfg, dict):
            raw_auth = pkg_cfg.get("auth")
            if isinstance(raw_auth, dict):
                auth_sec = dict(raw_auth)

        cli_auth = options.get("tunnel_auth")
        auth_mode = str(cli_auth or auth_sec.get("type") or "auto").strip().lower()

        # OIDC config
        oidc_sec: dict[str, Any] = {}
        raw_oidc = auth_sec.get("oidc")
        if isinstance(raw_oidc, dict):
            oidc_sec = dict(raw_oidc)

        oidc_provider = options.get("tunnel_oidc_provider") or oidc_sec.get("provider") or "google"
        oidc_email_domain = options.get("tunnel_oidc_email_domain")
        email_domains = [oidc_email_domain] if oidc_email_domain else oidc_sec.get("email_domains")

        oidc_config: dict[str, Any] | None = None
        if auth_mode == "oidc" or oidc_sec:
            oidc_config = {
                "provider": str(oidc_provider),
                "client_id": oidc_sec.get("client_id", ""),
                "client_secret_account": oidc_sec.get("client_secret_keyring_account", ""),
                "issuer_url": oidc_sec.get("issuer_url"),
                "email_domains": email_domains or ["*"],
            }

        # Basic Auth config
        basic_sec: dict[str, Any] = {}
        raw_basic = auth_sec.get("basic")
        if isinstance(raw_basic, dict):
            basic_sec = dict(raw_basic)

        basic_user = options.get("tunnel_basic_user") or basic_sec.get("username")
        basic_acct = options.get("tunnel_basic_keyring_account") or basic_sec.get("password_keyring_account")

        basic_creds: tuple[str, str] | None = None
        if auth_mode == "basic" or (basic_user and basic_acct):
            # Preflight will strictly validate presence and resolve password
            basic_creds = (str(basic_user or ""), str(basic_acct or ""))

        self.service = TunnelService(
            provider=provider,
            domain=domain,
            quick=quick,
            runner=runner,
            keyring_account=keyring_account,
            tailscale_mode=tailscale_mode,
            auth_mode=auth_mode,
            oidc_config=oidc_config,
            basic_creds=basic_creds,
            selected_services=selected_services,
            runtime=context.runtime,
            allow_insecure=allow_insecure,
        )

        context.tunnel_provider = self.service
        context.add_mode("tunnels")

    def on_preflight(self, context: RunContext) -> None:
        """Validate tunnel prerequisites and auth credentials fail-fast."""
        if not self.service or not self.service.is_enabled():
            return

        # 1. Validate Tunnel Provider Prerequisites
        validate_tunnel_prerequisites(
            tunnel_type=self.service.provider,
            domain=self.service.domain,
            quick=self.service.quick,
            runner=self.service.runner,
            keyring_account=self.service.keyring_account,
            tailscale_mode=self.service.tailscale_mode,
            runtime=self.service.runtime,
        )

        # 2. Validate Explicit Basic Auth Credentials if requested
        if self.service.auth_mode == "basic" or self.service.basic_creds:
            user = self.service.basic_creds[0] if self.service.basic_creds else None
            acct = self.service.basic_creds[1] if self.service.basic_creds else None
            clean_u, clean_p = validate_basic_auth_credentials(user, acct)
            # Store resolved password tuple
            self.service.basic_creds = (clean_u, clean_p)

        # 3. Validate OIDC Configuration if requested
        if self.service.auth_mode == "oidc" and self.service.oidc_config:
            resolved_oidc = validate_oidc_config(
                provider=self.service.oidc_config.get("provider"),
                client_id=self.service.oidc_config.get("client_id"),
                client_secret_account=self.service.oidc_config.get("client_secret_account"),
                issuer_url=self.service.oidc_config.get("issuer_url"),
                email_domains=self.service.oidc_config.get("email_domains"),
            )
            self.service.oidc_config.update(resolved_oidc)

    def on_container_configure(
        self,
        spec: ContainerRunSpec,
        context: RunContext,
    ) -> None:
        """Attach context ExitStack to TunnelService for on-demand endpoint provisioning."""
        if self.service and context.exit_stack:
            self.service.exit_stack = context.exit_stack

    def post_start(self, context: RunContext) -> None:
        """Render unified Ingress & Tunnel status table in the terminal."""
        if not self.service or not self.service.is_enabled() or not context.exit_stack:
            return

        # Ensure all registered endpoints have been started
        endpoints = self.service.provision_all(context.exit_stack)
        if not endpoints:
            return

        from logging_driver import LogDriver

        log_drv = LogDriver(context.project_dir)
        if log_drv.quiet:
            return

        provider_name = (
            "Cloudflare Quick Tunnels"
            if self.service.quick
            else (
                f"Cloudflare Tunnel ({self.service.domain})"
                if self.service.provider == "cloudflare"
                else "Tailscale Serve"
            )
        )

        log_drv.console.print(f"\n  [bold cyan]INGRESS & SECURE TUNNELS ({provider_name})[/bold cyan]")
        log_drv.console.print("  " + "─" * 85)
        log_drv.console.print(f"  {'Service':<12} {'Port':<8} {'Access Control':<28} {'Public Endpoint'}")
        log_drv.console.print("  " + "─" * 85)

        for name, ep in endpoints.items():
            port_str = str(ep.request.port)
            if ep.is_gated:
                if ep.auth_mode == "oidc":
                    domain = (
                        (self.service.oidc_config.get("email_domains") or ["*"])[0]
                        if self.service.oidc_config
                        else "SSO"
                    )
                    auth_str = f"[yellow]Gated (OIDC: {domain})[/yellow]"
                elif ep.auth_mode == "basic":
                    user = self.service.basic_creds[0] if self.service.basic_creds else "user"
                    auth_str = f"[yellow]Gated (Basic Auth: {user})[/yellow]"
                else:
                    auth_str = "[yellow]Gated (Session Token)[/yellow]"
            elif ep.auth_mode == "intrinsic":
                auth_str = "[green]Intrinsic (Pairing Token)[/green]"
            else:
                auth_str = "[dim]Direct (Unprotected)[/dim]"

            display_url = ep.public_url
            if ep.access_token:
                display_url = f"{ep.public_url}/?pa_token={ep.access_token}"

            clickable = f"[link={display_url}]{display_url}[/link]"
            log_drv.console.print(f"  {name:<12} {port_str:<8} {auth_str:<37} {clickable} 🔗")

        log_drv.console.print("  " + "─" * 85)
