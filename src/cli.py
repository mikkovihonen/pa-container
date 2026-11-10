from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

sys.dont_write_bytecode = True

from rich.console import Console
from rich.table import Table

SCRIPT_DIR: Path = Path(__file__).resolve().parent
REPO_ROOT: Path = SCRIPT_DIR.parent
PROJECT_DIR: Path = Path(os.environ.get("PROJECT_DIR", Path.cwd()))
from logging_driver import (
    LogCategory,
    clean_all_projects_logs,
    clean_project_logs,
    fail_and_render,
    get_category_logger,
    get_log_driver,
    init_log_driver,
    render_hard_error,
)
from project import get_project_logs_dir
from version import get_git_tag_version

cli_logger = get_category_logger("cli", LogCategory.PREFLIGHT)

# ─── Options Dataclasses ─────────────────────────────────────────────────────


@dataclass
class GlobalCliOptions:
    """Global flags available across all subcommands."""

    verbose: bool = False
    quiet: bool = False
    log_level: str | None = None
    log_file: Path | None = None
    no_color: bool = False


@dataclass
class RunOptions(GlobalCliOptions):
    """Options for the 'run' subcommand."""

    agent: str | None = None
    t3: bool = False
    t3_lan: bool = False
    t3_port: str | None = None
    t3_advertise_host: str | None = None
    t3_tunnel: str | None = None
    t3_tunnel_domain: str | None = None
    t3_tunnel_quick: bool = False
    t3_tunnel_runner: str | None = None
    t3_tunnel_keyring_account: str | None = None
    t3_tunnel_tailscale_mode: str | None = None
    t3_public_url: str | None = None
    open_browser: bool | None = None
    container_argv: list[str] = field(default_factory=list)


@dataclass
class ProxyOptions(GlobalCliOptions):
    """Options for the 'proxy' subcommand."""

    all: bool = False
    open: bool = False
    url: bool = False
    json: bool = False


@dataclass
class DesktopOptions(GlobalCliOptions):
    """Options for the 'desktop' subcommand."""

    all: bool = False
    open: bool = False
    url: bool = False
    vnc: bool = False
    json: bool = False


@dataclass
class InitOptions(GlobalCliOptions):
    """Options for the 'init' subcommand."""

    global_config: bool = False


@dataclass
class BuildOptions(GlobalCliOptions):
    """Options for the 'build' subcommand."""

    packages: str | None = None
    llama: bool = False
    llama_latest: bool = False
    llama_tag: str | None = None
    llama_backend: str | None = None
    no_clean: bool = False
    no_prune: bool = False
    clean: bool = False
    cmake_args: list[str] = field(default_factory=list)
    verify: bool = False


@dataclass
class TestOptions(GlobalCliOptions):
    """Options for the 'test' subcommand."""

    packages: str = "all"
    integration: bool = False


@dataclass
class CleanOptions(GlobalCliOptions):
    """Options for the 'clean' subcommand."""

    all: bool = False
    logs: bool = False
    build_cache: bool = False


@dataclass
class LogsOptions(GlobalCliOptions):
    """Options for the 'logs' subcommand."""

    action: str = "view"  # "view", "clean"
    follow: bool = False
    category: str | None = None
    build: bool = False
    path: bool = False
    list: bool = False
    lines: int | None = None
    # Clean sub-options
    all_projects: bool = False
    older_than: str | None = None
    force: bool = False


# ─── Parser Construction ────────────────────────────────────────────────────


def _parse_duration(duration_str: str) -> float:
    """Parse a human duration string (e.g., '7d', '24h', '30m') into seconds."""
    s = duration_str.strip().lower()
    if s.endswith("d"):
        return float(s[:-1]) * 86400
    if s.endswith("h"):
        return float(s[:-1]) * 3600
    if s.endswith("m"):
        return float(s[:-1]) * 60
    if s.endswith("s"):
        return float(s[:-1])
    return float(s) * 86400  # Default to days if unit omitted


def create_parser() -> argparse.ArgumentParser:
    """Construct the unified pa CLI argument parser."""
    version = get_git_tag_version(REPO_ROOT)
    if not version:
        raise RuntimeError("Unable to determine pa-container version from git tags.")

    # Shared global flags inherited across root and subcommands
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Enable verbose streaming output to terminal.",
    )
    common_parser.add_argument(
        "--quiet",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Suppress progress output; show errors only.",
    )
    common_parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=argparse.SUPPRESS,
        help="Override logging level (overrides configuration and LOG_LEVEL).",
    )
    common_parser.add_argument(
        "--log-file",
        type=Path,
        default=argparse.SUPPRESS,
        help="Explicitly specify the destination path for the session log file.",
    )
    common_parser.add_argument(
        "--no-color",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Disable ANSI color and cursor formatting.",
    )

    parser = argparse.ArgumentParser(
        prog="pa",
        parents=[common_parser],
        description="Containerized development environment with local LLM inference and traffic isolation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version}",
        help="Show program version and exit.",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    # ─── 'run' subcommand ────────────────────────────────────────────────────
    run_parser = subparsers.add_parser(
        "run",
        parents=[common_parser],
        help="Launch the containerized coding agent workspace.",
        description="Launch an isolated coding agent container with optional local LLM inference and pairing.",
    )
    run_parser.add_argument(
        "--agent",
        help=(
            "Coding agent driver(s) to launch. Accepts a single agent (e.g. 'opencode'), "
            "a comma-separated list (e.g. 'opencode,pi'), or 'all'. "
            "In T3 mode, defaults to all enabled agents if omitted. "
            "In standard CLI mode, launches the first agent interactively with secondary agents provisioned."
        ),
    )
    run_parser.add_argument(
        "--t3",
        action="store_true",
        help="Enable T3 Code web server mode inside the agent container.",
    )
    run_parser.add_argument(
        "--t3-lan",
        action="store_true",
        help="Allow T3 Code inbound connections from LAN devices (binds 0.0.0.0).",
    )
    run_parser.add_argument(
        "--t3-port",
        help="Port for T3 Code web server (integer or 'auto'). Defaults to 3773 or next available port if in use.",
    )
    run_parser.add_argument(
        "--t3-advertise-host",
        help="Hostname or IP address to advertise for T3 pairing (e.g. 'external' or IP).",
    )
    run_parser.add_argument(
        "--t3-tunnel",
        choices=["tailscale", "cloudflare"],
        help="Automated secure tunnel provider for remote T3 pairing.",
    )
    run_parser.add_argument(
        "--t3-tunnel-domain",
        help="Custom public hostname for Cloudflare tunnel.",
    )
    run_parser.add_argument(
        "--t3-tunnel-quick",
        action="store_true",
        help="Use a quick ephemeral trycloudflare tunnel without pre-created credentials.",
    )
    run_parser.add_argument(
        "--t3-tunnel-runner",
        choices=["auto", "container", "host"],
        default=None,
        help="Runner environment for cloudflared tunnel daemon.",
    )
    run_parser.add_argument(
        "--t3-tunnel-keyring-account",
        default=None,
        help="OS keyring credential account holding the Cloudflare tunnel token.",
    )
    run_parser.add_argument(
        "--t3-tunnel-tailscale-mode",
        choices=["serve", "funnel"],
        default=None,
        help="Tailscale exposure mode: 'serve' (tailnet-only) or 'funnel' (public internet).",
    )
    run_parser.add_argument(
        "--t3-public-url",
        help="Pre-existing public HTTPS URL override for T3 pairing link.",
    )
    run_parser.add_argument(
        "--open-browser",
        action="store_true",
        default=None,
        help="Automatically open mitmweb UI in the default web browser on launch.",
    )

    # ─── 'build' subcommand ──────────────────────────────────────────────────
    build_parser = subparsers.add_parser(
        "build",
        parents=[common_parser],
        help="Build container images, packages, or local llama-server.",
        description="Compile local packages, agent images, proxy images, or llama-server.",
    )
    build_parser.add_argument(
        "--packages",
        help="Comma-separated list of Agent Capability Packages to compile (or 'all').",
    )
    build_parser.add_argument(
        "--llama",
        action="store_true",
        help="Compile a minimal, optimized llama-server binary natively for host hardware.",
    )
    build_parser.add_argument(
        "--llama-latest",
        action="store_true",
        help="Query GitHub releases and build the latest tagged llama.cpp release.",
    )
    build_parser.add_argument(
        "--llama-tag",
        help="Specific git tag or release to compile for llama.cpp.",
    )
    build_parser.add_argument(
        "--llama-backend",
        help="Target hardware acceleration backend for llama.cpp (metal, cuda, rocm, cpu).",
    )
    build_parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip cleaning build directory before compiling llama.cpp.",
    )
    build_parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean orphaned containers, images, and build cache without building.",
    )
    build_parser.add_argument(
        "--no-prune",
        action="store_true",
        help="Skip automatic post-build dangling container image pruning.",
    )
    build_parser.add_argument(
        "--cmake-arg",
        action="append",
        dest="cmake_args",
        default=[],
        help="Additional CMake flag to pass to llama.cpp build (can be repeated).",
    )
    build_parser.add_argument(
        "--verify",
        action="store_true",
        help="Execute in-container smoke test verification for compiled packages.",
    )

    # ─── 'test' subcommand ───────────────────────────────────────────────────
    test_parser = subparsers.add_parser(
        "test",
        parents=[common_parser],
        help="Execute in-container verification and smoke tests for packages.",
        description="Run in-container smoke test verification across Agent Capability Packages.",
    )
    test_parser.add_argument(
        "--packages",
        default="all",
        help="Comma-separated list of Agent Capability Packages to verify (default: 'all').",
    )
    test_parser.add_argument(
        "--integration",
        action="store_true",
        default=False,
        help="Execute end-to-end integration tests (ephemeral container launch with runtime privileges) for packages.",
    )

    # ─── 'clean' subcommand ──────────────────────────────────────────────────
    clean_parser = subparsers.add_parser(
        "clean",
        parents=[common_parser],
        help="Clean orphaned containers, images, build cache, and logs.",
        description="Maintenance utility to sweep dead containers, prune images, and purge logs.",
    )
    clean_parser.add_argument(
        "--all",
        action="store_true",
        help="Clean orphaned containers, stale images, build cache, and project logs.",
    )
    clean_parser.add_argument(
        "--logs",
        action="store_true",
        help="Purge historical log files for this workspace.",
    )
    clean_parser.add_argument(
        "--build-cache",
        action="store_true",
        help="Purge container runtime layer build cache.",
    )

    # ─── 'logs' subcommand ───────────────────────────────────────────────────
    logs_parser = subparsers.add_parser(
        "logs",
        parents=[common_parser],
        help="Inspect, tail, list, or clean project log files.",
        description="Manage and view per-project execution and build logs.",
    )
    logs_parser.add_argument(
        "--follow",
        action="store_true",
        help="Follow active log file in real time (similar to tail -f).",
    )
    logs_parser.add_argument(
        "--category",
        help="Filter log lines by explicit category tag (e.g. 'build', 'proxy', 'server').",
    )
    logs_parser.add_argument(
        "--build",
        action="store_true",
        help="Target the latest container build log instead of the session run log.",
    )
    logs_parser.add_argument(
        "--path",
        action="store_true",
        help="Print the absolute path to this project's logs directory and exit.",
    )
    logs_parser.add_argument(
        "--list",
        action="store_true",
        help="List all log files for this project with sizes and modification times.",
    )
    logs_parser.add_argument(
        "--lines",
        type=int,
        default=None,
        help="Number of lines to display from the log tail.",
    )

    logs_subparsers = logs_parser.add_subparsers(dest="logs_subcommand")
    clean_logs_parser = logs_subparsers.add_parser(
        "clean",
        parents=[common_parser],
        help="Purge historical log files.",
    )
    clean_logs_parser.add_argument(
        "--all-projects",
        action="store_true",
        help="Purge historical logs across all workspaces in ~/.local/state/pa-container/projects/.",
    )
    clean_logs_parser.add_argument(
        "--older-than",
        help="Purge logs older than duration (e.g. '7d', '24h', '30m').",
    )
    clean_logs_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip interactive confirmation before deleting files.",
    )

    # ─── 'proxy' subcommand ──────────────────────────────────────────────────
    proxy_parser = subparsers.add_parser(
        "proxy",
        parents=[common_parser],
        help="Inspect active proxy containers and mitmweb UI endpoints.",
        description="Query active proxy containers for this project or globally, showing clickable links and status.",
    )
    proxy_parser.add_argument(
        "--all",
        action="store_true",
        help="List all active proxy containers across all projects.",
    )
    proxy_parser.add_argument(
        "--open",
        action="store_true",
        help="Open the mitmweb UI in the default OS web browser.",
    )
    proxy_parser.add_argument(
        "--url",
        action="store_true",
        help="Print only the mitmweb URL (for shell scripts or piping).",
    )
    proxy_parser.add_argument(
        "--json",
        action="store_true",
        help="Output proxy metadata in JSON format.",
    )

    # ─── 'desktop' subcommand ────────────────────────────────────────────────
    desktop_parser = subparsers.add_parser(
        "desktop",
        parents=[common_parser],
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

    # ─── 'init' subcommand ───────────────────────────────────────────────────
    init_parser = subparsers.add_parser(
        "init",
        parents=[common_parser],
        help="Initialize project or global configuration from templates.",
        description="Seed configuration files from templates into the workspace or user config directory.",
    )
    init_parser.add_argument(
        "--global",
        dest="global_config",
        action="store_true",
        help="Initialize global configuration (~/.config/pa-container/config.yaml) instead of local project.",
    )

    return parser


# ─── CLI Entrypoint Execution ────────────────────────────────────────────────


def parse_cli_args(argv: Sequence[str] | None = None) -> tuple[str, Any]:
    """Parse command line arguments into a (command, options_dataclass) tuple.

    Handles POSIX '--' container passthrough cleanly.
    """
    raw_args = list(argv if argv is not None else sys.argv[1:])

    # Extract passthrough arguments after '--'
    passthrough_args: list[str] = []
    if "--" in raw_args:
        idx = raw_args.index("--")
        passthrough_args = raw_args[idx + 1 :]
        raw_args = raw_args[:idx]

    # Normalize '--cmake-arg val' to '--cmake-arg=val' so values beginning with '-' aren't rejected
    normalized_args: list[str] = []
    i = 0
    while i < len(raw_args):
        if raw_args[i] == "--cmake-arg" and i + 1 < len(raw_args):
            normalized_args.append(f"--cmake-arg={raw_args[i + 1]}")
            i += 2
        else:
            normalized_args.append(raw_args[i])
            i += 1
    raw_args = normalized_args

    parser = create_parser()

    if not raw_args:
        parser.print_help()
        sys.exit(0)

    args, unknown = parser.parse_known_args(raw_args)

    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")

    cmd = args.command

    # Global options
    verbose: bool = bool(getattr(args, "verbose", False))
    quiet: bool = bool(getattr(args, "quiet", False))
    log_level: str | None = getattr(args, "log_level", None)
    log_file: Path | None = getattr(args, "log_file", None)
    no_color: bool = bool(getattr(args, "no_color", False))

    if cmd == "run":
        options = RunOptions(
            verbose=verbose,
            quiet=quiet,
            log_level=log_level,
            log_file=log_file,
            no_color=no_color,
            agent=getattr(args, "agent", None),
            t3=getattr(args, "t3", False),
            t3_lan=getattr(args, "t3_lan", False),
            t3_port=getattr(args, "t3_port", None),
            t3_advertise_host=getattr(args, "t3_advertise_host", None),
            t3_tunnel=getattr(args, "t3_tunnel", None),
            t3_tunnel_domain=getattr(args, "t3_tunnel_domain", None),
            t3_tunnel_quick=getattr(args, "t3_tunnel_quick", False),
            t3_tunnel_runner=getattr(args, "t3_tunnel_runner", None),
            t3_tunnel_keyring_account=getattr(args, "t3_tunnel_keyring_account", None),
            t3_tunnel_tailscale_mode=getattr(args, "t3_tunnel_tailscale_mode", None),
            t3_public_url=getattr(args, "t3_public_url", None),
            open_browser=getattr(args, "open_browser", None),
            container_argv=passthrough_args,
        )
        return "run", options

    if cmd == "build":
        b_options = BuildOptions(
            verbose=verbose,
            quiet=quiet,
            log_level=log_level,
            log_file=log_file,
            no_color=no_color,
            packages=getattr(args, "packages", None),
            llama=getattr(args, "llama", False),
            llama_latest=getattr(args, "llama_latest", False),
            llama_tag=getattr(args, "llama_tag", None),
            llama_backend=getattr(args, "llama_backend", None),
            no_clean=getattr(args, "no_clean", False),
            no_prune=getattr(args, "no_prune", False),
            clean=getattr(args, "clean", False),
            cmake_args=getattr(args, "cmake_args", []) or [],
            verify=getattr(args, "verify", False),
        )
        return "build", b_options

    if cmd == "test":
        t_options = TestOptions(
            verbose=verbose,
            quiet=quiet,
            log_level=log_level,
            log_file=log_file,
            no_color=no_color,
            packages=getattr(args, "packages", "all") or "all",
            integration=getattr(args, "integration", False),
        )
        return "test", t_options

    if cmd == "clean":
        c_options = CleanOptions(
            verbose=verbose,
            quiet=quiet,
            log_level=log_level,
            log_file=log_file,
            no_color=no_color,
            all=getattr(args, "all", False),
            logs=getattr(args, "logs", False) or getattr(args, "all", False),
            build_cache=getattr(args, "build_cache", False) or getattr(args, "all", False),
        )
        return "clean", c_options

    if cmd == "logs":
        l_subcmd = getattr(args, "logs_subcommand", None)
        l_options = LogsOptions(
            verbose=verbose,
            quiet=quiet,
            log_level=log_level,
            log_file=log_file,
            no_color=no_color,
            action="clean" if l_subcmd == "clean" else "view",
            follow=getattr(args, "follow", False),
            category=getattr(args, "category", None),
            build=getattr(args, "build", False),
            path=getattr(args, "path", False),
            list=getattr(args, "list", False),
            lines=getattr(args, "lines", None),
            all_projects=getattr(args, "all_projects", False),
            older_than=getattr(args, "older_than", None),
            force=getattr(args, "force", False),
        )
        return "logs", l_options

    if cmd == "proxy":
        p_options = ProxyOptions(
            verbose=verbose,
            quiet=quiet,
            log_level=log_level,
            log_file=log_file,
            no_color=no_color,
            all=bool(getattr(args, "all", False)),
            open=bool(getattr(args, "open", False)),
            url=bool(getattr(args, "url", False)),
            json=bool(getattr(args, "json", False)),
        )
        return cmd, p_options

    if cmd == "desktop":
        d_options = DesktopOptions(
            verbose=verbose,
            quiet=quiet,
            log_level=log_level,
            log_file=log_file,
            no_color=no_color,
            all=bool(getattr(args, "all", False)),
            open=bool(getattr(args, "open", False)),
            url=bool(getattr(args, "url", False)),
            vnc=bool(getattr(args, "vnc", False)),
            json=bool(getattr(args, "json", False)),
        )
        return cmd, d_options

    if cmd == "init":
        i_options = InitOptions(
            verbose=verbose,
            quiet=quiet,
            log_level=log_level,
            log_file=log_file,
            no_color=no_color,
            global_config=bool(getattr(args, "global_config", False)),
        )
        return cmd, i_options

    return cmd, args


# ─── Subcommand Handlers ─────────────────────────────────────────────────────


def handle_proxy_command(options: ProxyOptions) -> int:
    """Execute the 'proxy' / 'proxies' subcommand actions."""
    import json as json_module
    import webbrowser

    from network import get_project_proxy, list_active_proxies

    console = Console(no_color=options.no_color)
    is_in_project = (PROJECT_DIR / ".pa-container").exists() or (PROJECT_DIR / "config.yaml").exists()

    # If --all is requested, or if executed outside of any project workspace, list all active proxies
    if options.all or not is_in_project:
        proxies = list_active_proxies()

        if options.json:
            data = [
                {
                    "project_name": p.project_name,
                    "project_path": str(p.project_path) if p.project_path else None,
                    "project_hash": p.project_hash,
                    "container_name": p.container_name,
                    "mitmweb_port": p.mitmweb_port,
                    "mitmweb_url": p.mitmweb_url,
                    "is_healthy": p.is_healthy,
                    "active_clients": p.active_clients,
                    "created_at": p.created_at,
                }
                for p in proxies
            ]
            console.print(json_module.dumps(data, indent=2))
            return 0

        if options.url:
            for p in proxies:
                if p.mitmweb_url:
                    console.print(p.mitmweb_url)
            return 0

        if not proxies:
            console.print("[dim]No active pa-container proxies found on this system.[/dim]")
            return 0

        table = Table(title="Active pa-container Proxies", box=None)
        table.add_column("Project", style="bold cyan")
        table.add_column("Proxy Container")
        table.add_column("Status")
        table.add_column("mitmweb UI")
        table.add_column("Clients", justify="right")

        for p in proxies:
            status_str = "[green]Healthy[/green]" if p.is_healthy else "[yellow]Unreachable[/yellow]"
            url_str = (
                f"[link={p.mitmweb_url}]{p.mitmweb_url}[/link] [dim]🔗[/dim]" if p.mitmweb_url else "[dim]None[/dim]"
            )
            table.add_row(
                p.project_name,
                p.container_name,
                status_str,
                url_str,
                str(p.active_clients),
            )

        console.print(table)

        if options.open:
            for p in proxies:
                if p.mitmweb_url:
                    webbrowser.open(p.mitmweb_url)
        return 0

    # Project-specific query
    proxy_info = get_project_proxy(PROJECT_DIR)

    if options.json:
        if not proxy_info:
            console.print(json_module.dumps({"status": "inactive", "project": PROJECT_DIR.name}))
            return 1
        data_single = {
            "status": "running",
            "project_name": proxy_info.project_name,
            "project_path": str(proxy_info.project_path) if proxy_info.project_path else None,
            "project_hash": proxy_info.project_hash,
            "container_name": proxy_info.container_name,
            "mitmweb_port": proxy_info.mitmweb_port,
            "mitmweb_url": proxy_info.mitmweb_url,
            "is_healthy": proxy_info.is_healthy,
            "active_clients": proxy_info.active_clients,
        }
        console.print(json_module.dumps(data_single, indent=2))
        return 0

    if not proxy_info:
        from project import project_key

        key = project_key(PROJECT_DIR)
        console.print(
            f"[yellow]No active proxy container running for project '{PROJECT_DIR.name}' (pa-container-proxy-{key}).[/yellow]"
        )
        console.print("[dim]Run 'pa run' to start this project or use '--all' to view all proxies.[/dim]")
        return 1

    if options.url:
        if proxy_info.mitmweb_url:
            console.print(proxy_info.mitmweb_url)
            return 0
        console.print("[red]mitmweb port not published[/red]")
        return 1

    health_str = "[green]Healthy (HTTP 200)[/green]" if proxy_info.is_healthy else "[yellow]Unreachable[/yellow]"
    url_str = (
        f"[bold cyan][link={proxy_info.mitmweb_url}]{proxy_info.mitmweb_url}[/link][/bold cyan] [dim]🔗 (click to open)[/dim]"
        if proxy_info.mitmweb_url
        else "[dim]Not published[/dim]"
    )

    console.print(f"[bold]Project:[/bold]     {proxy_info.project_name} ([dim]{proxy_info.project_path}[/dim])")
    console.print(f"[bold]Proxy:[/bold]       {proxy_info.container_name} ([green]running[/green])")
    console.print(f"[bold]mitmweb UI:[/bold]  {url_str}")
    console.print(f"[bold]Health:[/bold]      {health_str}")
    console.print(f"[bold]Clients:[/bold]     {proxy_info.active_clients} active session(s)")

    if options.open and proxy_info.mitmweb_url:
        webbrowser.open(proxy_info.mitmweb_url)

    return 0


def handle_desktop_command(options: DesktopOptions) -> int:
    """Execute the 'desktop' / 'desktops' subcommand actions."""
    import json as json_module
    import webbrowser

    from desktop import get_project_desktop, list_active_desktops

    console = Console(no_color=options.no_color)
    is_in_project = (PROJECT_DIR / ".pa-container").exists() or (PROJECT_DIR / "config.yaml").exists()

    # If --all is requested, or if executed outside of any project workspace, list all active desktops
    if options.all or not is_in_project:
        desktops = list_active_desktops()

        if options.json:
            data = [
                {
                    "project_name": d.project_name,
                    "project_path": str(d.project_path) if d.project_path else None,
                    "project_hash": d.project_hash,
                    "container_name": d.container_name,
                    "novnc_port": d.novnc_port,
                    "novnc_url": d.novnc_url,
                    "vnc_port": d.vnc_port,
                    "vnc_endpoint": d.vnc_endpoint,
                    "display": d.display,
                    "is_healthy": d.is_healthy,
                    "created_at": d.created_at,
                }
                for d in desktops
            ]
            console.print(json_module.dumps(data, indent=2))
            return 0

        if options.url:
            for d in desktops:
                if d.novnc_url:
                    console.print(d.novnc_url)
            return 0

        if options.vnc:
            for d in desktops:
                if d.vnc_endpoint:
                    console.print(d.vnc_endpoint)
            return 0

        if not desktops:
            console.print("[dim]No active pa-container virtual desktops found on this system.[/dim]")
            return 0

        table = Table(title="Active pa-container Desktops", box=None)
        table.add_column("Project", style="bold cyan")
        table.add_column("Container")
        table.add_column("Status")
        table.add_column("noVNC Web UI")
        table.add_column("VNC Endpoint")

        for d in desktops:
            status_str = "[green]Healthy[/green]" if d.is_healthy else "[yellow]Unreachable[/yellow]"
            url_str = f"[link={d.novnc_url}]{d.novnc_url}[/link] [dim]🔗[/dim]" if d.novnc_url else "[dim]None[/dim]"
            vnc_str = f"[bold]{d.vnc_endpoint}[/bold]" if d.vnc_endpoint else "[dim]None[/dim]"
            table.add_row(
                d.project_name,
                d.container_name,
                status_str,
                url_str,
                vnc_str,
            )

        console.print(table)

        if options.open:
            for d in desktops:
                if d.novnc_url:
                    webbrowser.open(d.novnc_url)
        return 0

    # Project-specific query
    from images import read_project_packages

    active_pkgs = read_project_packages(PROJECT_DIR)
    if "virtual-desktop" not in active_pkgs:
        console.print(
            "[bold red]Error:[/bold red] The 'desktop' subcommand requires the 'virtual-desktop' capability package, but it is not enabled in .pa-container/config.yaml.\n\n"
            "To enable this capability, add 'virtual-desktop' to the 'packages:' list in your .pa-container/config.yaml:\n"
            "    packages:\n"
            "        - virtual-desktop"
        )
        return 1

    desktop_info = get_project_desktop(PROJECT_DIR)

    if options.json:
        if not desktop_info:
            console.print(json_module.dumps({"status": "inactive", "project": PROJECT_DIR.name}))
            return 1
        data_single = {
            "status": "running",
            "project_name": desktop_info.project_name,
            "project_path": str(desktop_info.project_path) if desktop_info.project_path else None,
            "project_hash": desktop_info.project_hash,
            "container_name": desktop_info.container_name,
            "novnc_port": desktop_info.novnc_port,
            "novnc_url": desktop_info.novnc_url,
            "vnc_port": desktop_info.vnc_port,
            "vnc_endpoint": desktop_info.vnc_endpoint,
            "display": desktop_info.display,
            "is_healthy": desktop_info.is_healthy,
        }
        console.print(json_module.dumps(data_single, indent=2))
        return 0

    if options.url:
        if desktop_info and desktop_info.novnc_url:
            console.print(desktop_info.novnc_url)
            return 0
        console.print("[red]noVNC port not published[/red]")
        return 1

    if options.vnc:
        if desktop_info and desktop_info.vnc_endpoint:
            console.print(desktop_info.vnc_endpoint)
            return 0
        console.print("[red]VNC port not published[/red]")
        return 1

    if not desktop_info:
        console.print(f"[yellow]No active virtual desktop running for project '{PROJECT_DIR.name}'.[/yellow]")
        console.print(
            "[dim]Ensure 'desktop.enabled: true' in .pa-container/config.yaml and run 'pa run' to start.[/dim]"
        )
        return 1

    status_str = "[green]Healthy[/green]" if desktop_info.is_healthy else "[yellow]Unreachable[/yellow]"
    url_str = (
        f"[bold cyan][link={desktop_info.novnc_url}]{desktop_info.novnc_url}[/link][/bold cyan] [dim]🔗 (click to open)[/dim]"
        if desktop_info.novnc_url
        else "[dim]Not published[/dim]"
    )
    vnc_str = f"[bold]{desktop_info.vnc_endpoint}[/bold]" if desktop_info.vnc_endpoint else "[dim]Not published[/dim]"

    console.print(f"[bold]Project:[/bold]       {desktop_info.project_name} ([dim]{desktop_info.project_path}[/dim])")
    console.print(f"[bold]Container:[/bold]     {desktop_info.container_name} ([green]running[/green])")
    console.print(f"[bold]Display:[/bold]       {desktop_info.display}")
    console.print(f"[bold]noVNC Web UI:[/bold]  {url_str}")
    console.print(f"[bold]VNC Endpoint:[/bold]  {vnc_str}")
    console.print(f"[bold]Health:[/bold]        {status_str}")

    if options.open and desktop_info.novnc_url:
        webbrowser.open(desktop_info.novnc_url)

    return 0


def handle_logs_command(options: LogsOptions) -> int:
    """Execute the 'logs' subcommand actions."""
    console = Console(no_color=options.no_color)
    project_logs = get_project_logs_dir(PROJECT_DIR)

    if options.path:
        console.print(str(project_logs))
        return 0

    if options.list:
        if not project_logs.is_dir():
            console.print("[dim]No logs found for this project.[/dim]")
            return 0

        files = sorted(
            [f for f in project_logs.iterdir() if f.is_file() and not f.is_symlink()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files:
            console.print("[dim]No log files found.[/dim]")
            return 0

        table = Table(title=f"Log Files: {PROJECT_DIR.name}", box=None)
        table.add_column("Filename", style="bold cyan")
        table.add_column("Size", justify="right")
        table.add_column("Modified")

        for f in files:
            st = f.stat()
            size_kb = st.st_size / 1024
            mtime_str = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            table.add_row(f.name, f"{size_kb:.1f} KiB", mtime_str)

        console.print(table)
        return 0

    if options.action == "clean":
        seconds = _parse_duration(options.older_than) if options.older_than else None
        if options.all_projects:
            if not options.force:
                console.print(
                    "[bold yellow]Warning:[/bold yellow] Purging logs across ALL projects in ~/.local/state/pa-container/projects/."
                )
            deleted = clean_all_projects_logs(older_than_seconds=seconds)
            console.print(f"Purged {len(deleted)} log file(s) across all projects.")
            return 0

        deleted = clean_project_logs(PROJECT_DIR, older_than_seconds=seconds)
        console.print(f"Purged {len(deleted)} log file(s) for project '{PROJECT_DIR.name}'.")
        return 0

    # Default: view or follow log tail
    target_symlink = project_logs / ("latest-build.log" if options.build else "latest.log")
    if not target_symlink.exists():
        console.print(f"[yellow]No {'build' if options.build else 'run'} log found for this project.[/yellow]")
        return 0

    target_file = target_symlink.resolve()

    if options.follow:
        try:
            with target_file.open("r", encoding="utf-8", errors="replace") as log_file_io:
                log_file_io.seek(0, os.SEEK_END)
                while True:
                    line = log_file_io.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    if options.category:
                        cat_tag = f"[{options.category}]"
                        if cat_tag not in line:
                            continue
                    console.print(line, end="")
        except KeyboardInterrupt:
            return 0
    else:
        try:
            lines = target_file.read_text(encoding="utf-8", errors="replace").splitlines()
            if options.category:
                cat_tag = f"[{options.category}]"
                lines = [line_text for line_text in lines if cat_tag in line_text]
            tail_lines = lines[-options.lines :] if options.lines is not None else lines
            for line in tail_lines:
                console.print(line)
        except OSError as e:
            cli_logger.error(f"Could not read log file: {e}", exc_info=True)
            console.print(f"[red]Could not read log file: {e}[/red]")
            return 1

    return 0


def handle_init_command(options: InitOptions) -> int:
    """Initialize configuration from templates."""
    console = Console(stderr=False)
    try:
        if options.global_config:
            from global_config import init_global_config

            target = init_global_config()
            console.print(f"[green]Initialized global configuration at {target}[/green]")
        else:
            from project import init_project_config

            target = init_project_config()
            console.print(f"[green]Initialized project configuration at {target}[/green]")
        return 0
    except Exception as e:
        cli_logger.error(f"Init command failed: {e}", exc_info=True)
        console.print(f"[red]Error initializing configuration: {e}[/red]")
        return 1


def main(argv: Sequence[str] | None = None) -> None:
    """Unified CLI dispatcher."""
    try:
        cmd, options = parse_cli_args(argv)
        if not cmd:
            return

        if cmd == "init":
            sys.exit(handle_init_command(options))
            return

        if cmd == "logs":
            sys.exit(handle_logs_command(options))
            return

        if cmd == "proxy":
            sys.exit(handle_proxy_command(options))
            return

        if cmd == "desktop":
            sys.exit(handle_desktop_command(options))
            return

        if cmd == "run":
            t3_requested = any(
                [
                    getattr(options, "t3", False),
                    getattr(options, "t3_lan", False),
                    getattr(options, "t3_port", None) is not None,
                    getattr(options, "t3_advertise_host", None) is not None,
                    getattr(options, "t3_tunnel", None) is not None,
                    getattr(options, "t3_tunnel_domain", None) is not None,
                    getattr(options, "t3_tunnel_quick", False),
                    getattr(options, "t3_tunnel_runner", None) is not None,
                    getattr(options, "t3_tunnel_keyring_account", None) is not None,
                    getattr(options, "t3_tunnel_tailscale_mode", None) is not None,
                    getattr(options, "t3_public_url", None) is not None,
                ]
            )
            if t3_requested:
                from images import read_project_packages

                active_pkgs = read_project_packages(PROJECT_DIR)
                if "t3" not in active_pkgs:
                    Console(stderr=True).print(
                        "[bold red]Error:[/bold red] The '--t3' option requires the 't3' capability package, but it is not enabled in .pa-container/config.yaml.\n\n"
                        "To enable this capability, add 't3' to the 'packages:' list in your .pa-container/config.yaml:\n"
                        "    packages:\n"
                        "        - t3"
                    )
                    sys.exit(1)
                    return

        # Initialize log driver for 'run' and 'build' commands
        from global_config import load_global_config

        try:
            global_cfg = load_global_config(repo_root=REPO_ROOT)
        except FileNotFoundError as e:
            cli_logger.error(f"Global configuration missing: {e}", exc_info=True)
            render_hard_error(
                LogCategory.PREFLIGHT,
                "Missing Global Configuration",
                str(e),
                hints=[
                    "Initialize global configuration: pa init --global",
                    "Or create ~/.config/pa-container/config.yaml manually.",
                ],
            )
            sys.exit(1)
            return
        except ValueError as e:
            cli_logger.error(f"Global configuration invalid: {e}", exc_info=True)
            render_hard_error(
                LogCategory.PREFLIGHT,
                "Invalid Global Configuration",
                str(e),
                hints=["Inspect and fix errors in ~/.config/pa-container/config.yaml."],
            )
            sys.exit(1)
            return

        project_logging: dict[str, Any] = {}
        pa_container_dir = PROJECT_DIR / ".pa-container"
        if (pa_container_dir / "config.yaml").is_file():
            try:
                from network import read_logging_config

                project_logging = dict(read_logging_config(pa_container_dir))
            except Exception:
                project_logging = {}

        proj_retention = project_logging.get("retention") or {}
        eff_max_days = (
            proj_retention.get("max_days")
            if proj_retention.get("max_days") is not None
            else global_cfg.logging.retention.max_days
        )
        eff_max_launches = (
            proj_retention.get("max_launches")
            if proj_retention.get("max_launches") is not None
            else global_cfg.logging.retention.max_launches
        )
        eff_log_level = (
            getattr(options, "log_level", None)
            or os.environ.get("LOG_LEVEL")
            or project_logging.get("log_level")
            or global_cfg.logging.log_level
            or global_cfg.runtime.log_level
        )

        driver = init_log_driver(
            PROJECT_DIR,
            log_level=eff_log_level,
            verbose=getattr(options, "verbose", False),
            quiet=getattr(options, "quiet", False),
            no_color=getattr(options, "no_color", False),
            log_file=getattr(options, "log_file", None),
            max_days=eff_max_days,
            max_launches=eff_max_launches,
        )

        if cmd == "clean":
            if getattr(options, "logs", False):
                deleted = clean_project_logs(PROJECT_DIR)
                driver.console.print(f"Purged {len(deleted)} log file(s).")
            # Forward to build.clean_pass
            from build import run_clean_pass

            sys.exit(run_clean_pass(purge_cache=getattr(options, "build_cache", False)))
            return

        if cmd == "build":
            if getattr(options, "clean", False):
                from build import run_clean_pass

                sys.exit(run_clean_pass(purge_cache=True))
                return

            from build import execute_build

            sys.exit(execute_build(options, driver=driver))
            return

        if cmd == "test":
            from build import execute_test

            sys.exit(execute_test(options, driver=driver))
            return

        if cmd == "run":
            from run import execute_run

            sys.exit(execute_run(options, driver=driver))
            return

    except KeyboardInterrupt:
        active_driver = get_log_driver()
        if active_driver is not None:
            active_driver.pause_for_interactive()
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as fatal_err:
        cli_logger.error(f"Fatal unhandled CLI exception: {fatal_err}", exc_info=True)
        fail_and_render(
            LogCategory.PREFLIGHT,
            "Fatal CLI Error",
            str(fatal_err),
            exc=fatal_err,
            source_logger=cli_logger,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
