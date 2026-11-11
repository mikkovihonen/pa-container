from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .types import DesktopConfig

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from network import load_project_config, query_container_port

logger = get_category_logger(__name__, LogCategory.DESKTOP)


def read_desktop_config(config_dir: Path | None = None) -> DesktopConfig:
    """Read and validate the desktop configuration from project config.yaml."""
    cfg = load_project_config(config_dir)
    packages_list = cfg.get("packages")
    section = None
    if isinstance(packages_list, list):
        for item in packages_list:
            if isinstance(item, dict) and "virtual-desktop" in item:
                val = item["virtual-desktop"]
                if isinstance(val, dict):
                    section = val.get("config", {})
                    break

    if section is None:
        raise ValueError("Missing required 'virtual-desktop' package configuration in project config")

    for key in ("resolution", "compositor", "vnc", "novnc", "open_browser", "gpu"):
        if key not in section:
            raise ValueError(f"Missing required 'virtual-desktop.config.{key}' configuration in project config")

    enabled = section.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"Invalid 'virtual-desktop.enabled': expected bool, got {type(enabled).__name__}")

    resolution = str(section["resolution"]).strip()
    if not re.match(r"^\d+x\d+$", resolution):
        raise ValueError(f"Invalid 'virtual-desktop.resolution': expected WIDTHxHEIGHT format, got {resolution!r}")

    compositor = str(section["compositor"]).strip().lower()
    if compositor not in ("labwc",):
        raise ValueError(f"Invalid 'virtual-desktop.compositor': unsupported compositor {compositor!r}")

    open_browser = section["open_browser"]
    if not isinstance(open_browser, bool):
        raise ValueError(f"Invalid 'virtual-desktop.open_browser': expected bool, got {type(open_browser).__name__}")

    # VNC endpoint settings
    vnc_sec = section["vnc"]
    if not isinstance(vnc_sec, dict):
        raise ValueError("Invalid 'desktop.vnc': expected mapping")
    for k in ("enabled", "port", "expose"):
        if k not in vnc_sec:
            raise ValueError(f"Missing required 'desktop.vnc.{k}'")
    vnc_enabled = vnc_sec["enabled"]
    if not isinstance(vnc_enabled, bool):
        raise ValueError("Invalid 'desktop.vnc.enabled': expected bool")
    vnc_port = vnc_sec["port"]
    if vnc_port != "auto":
        try:
            vnc_port = int(vnc_port)
            if not (1 <= vnc_port <= 65535):
                raise ValueError()
        except ValueError, TypeError:
            raise ValueError(
                f"Invalid 'desktop.vnc.port': expected 'auto' or 1..65535, got {vnc_sec['port']!r}"
            ) from None
    vnc_expose = str(vnc_sec["expose"]).strip().lower()
    if vnc_expose not in ("localhost", "lan"):
        raise ValueError(f"Invalid 'desktop.vnc.expose': expected 'localhost' or 'lan', got {vnc_expose!r}")

    # noVNC endpoint settings
    novnc_sec = section["novnc"]
    if not isinstance(novnc_sec, dict):
        raise ValueError("Invalid 'desktop.novnc': expected mapping")
    for k in ("enabled", "port", "expose"):
        if k not in novnc_sec:
            raise ValueError(f"Missing required 'desktop.novnc.{k}'")
    novnc_enabled = novnc_sec["enabled"]
    if not isinstance(novnc_enabled, bool):
        raise ValueError("Invalid 'desktop.novnc.enabled': expected bool")
    novnc_port = novnc_sec["port"]
    if novnc_port != "auto":
        try:
            novnc_port = int(novnc_port)
            if not (1 <= novnc_port <= 65535):
                raise ValueError()
        except ValueError, TypeError:
            raise ValueError(
                f"Invalid 'desktop.novnc.port': expected 'auto' or 1..65535, got {novnc_sec['port']!r}"
            ) from None
    novnc_expose = str(novnc_sec["expose"]).strip().lower()
    if novnc_expose not in ("localhost", "lan"):
        raise ValueError(f"Invalid 'desktop.novnc.expose': expected 'localhost' or 'lan', got {novnc_expose!r}")

    # GPU settings
    gpu_sec = section["gpu"]
    if not isinstance(gpu_sec, dict) or "enabled" not in gpu_sec:
        raise ValueError("Invalid 'desktop.gpu': expected mapping with 'enabled'")
    gpu_enabled = gpu_sec["enabled"]
    if gpu_enabled not in ("auto", True, False):
        raise ValueError(f"Invalid 'desktop.gpu.enabled': expected 'auto', true, or false, got {gpu_enabled!r}")

    return {
        "enabled": enabled,
        "resolution": resolution,
        "compositor": compositor,
        "open_browser": open_browser,
        "vnc": {
            "enabled": vnc_enabled,
            "port": vnc_port,
            "expose": vnc_expose,
        },
        "novnc": {
            "enabled": novnc_enabled,
            "port": novnc_port,
            "expose": novnc_expose,
        },
        "gpu": {
            "enabled": gpu_enabled,
        },
    }


from util import is_port_available


def resolve_desktop_ports(cfg: DesktopConfig) -> tuple[int, int]:
    """Resolve host ports for noVNC and VNC, handling 'auto' or busy ports."""
    from util import get_free_port

    novnc_cfg = cfg.get("novnc") or {}
    vnc_cfg = cfg.get("vnc") or {}

    configured_novnc = novnc_cfg.get("port", "auto")
    if configured_novnc == "auto":
        novnc_port = get_free_port()
    elif isinstance(configured_novnc, int) and is_port_available(configured_novnc):
        novnc_port = configured_novnc
    else:
        logger.warning(f"Configured noVNC port {configured_novnc} is in use; allocating ephemeral port.")
        novnc_port = get_free_port()

    configured_vnc = vnc_cfg.get("port", "auto")
    if configured_vnc == "auto":
        vnc_port = get_free_port()
    elif isinstance(configured_vnc, int) and is_port_available(configured_vnc) and configured_vnc != novnc_port:
        vnc_port = configured_vnc
    else:
        logger.warning(f"Configured VNC port {configured_vnc} is in use or conflicts; allocating ephemeral port.")
        vnc_port = get_free_port()

    return novnc_port, vnc_port


@dataclass(frozen=True)
class ActiveDesktopInfo:
    """Status and connection details for an active virtual desktop container."""

    project_name: str
    project_path: Path | None
    project_hash: str
    container_name: str
    novnc_port: int | None
    novnc_url: str | None
    vnc_port: int | None
    vnc_endpoint: str | None
    display: str
    is_healthy: bool
    created_at: str | None


def check_desktop_health(url: str | None, timeout: float = 1.0) -> bool:
    """Check if the noVNC endpoint URL responds to an HTTP request."""
    if not url:
        return False
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except urllib.error.HTTPError as e:
        return 200 <= e.code < 500
    except Exception as e:
        logger.debug(f"Desktop health check failed for {url}: {e}")
        return False


def get_project_desktop(
    project_dir: Path,
    runtime: str | None = None,
) -> ActiveDesktopInfo | None:
    """Return active desktop info for a specific project directory, or None if not running with desktop."""
    from project import project_key

    runtime_bin = runtime or "podman"
    proj_hash = project_key(project_dir)

    try:
        proc = subprocess.run(
            [
                runtime_bin,
                "ps",
                "--filter",
                f"label=pa-container.project.hash={proj_hash}",
                "--filter",
                "label=pa-container.type=agent",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None

        raw = json.loads(proc.stdout)
        containers = raw if isinstance(raw, list) else [raw]
        if not containers:
            return None

        c = containers[0]
        names = c.get("Names") or []
        if isinstance(names, str):
            names = [names]
        container_name = names[0].lstrip("/") if names else f"pa-container-agent-{proj_hash}"

        novnc_port = query_container_port(runtime_bin, container_name, 6080)
        vnc_port = query_container_port(runtime_bin, container_name, 5900)

        # If neither port is exposed, desktop is not active in this container
        if not novnc_port and not vnc_port:
            return None

        novnc_url = f"http://127.0.0.1:{novnc_port}/vnc.html?autoconnect=true&resize=scale" if novnc_port else None
        vnc_endpoint = f"127.0.0.1:{vnc_port}" if vnc_port else None
        is_healthy = check_desktop_health(novnc_url)
        created_at = c.get("Created") or c.get("CreatedAt")

        return ActiveDesktopInfo(
            project_name=project_dir.resolve().name,
            project_path=project_dir.resolve(),
            project_hash=proj_hash,
            container_name=container_name,
            novnc_port=novnc_port,
            novnc_url=novnc_url,
            vnc_port=vnc_port,
            vnc_endpoint=vnc_endpoint,
            display="wayland-0",
            is_healthy=is_healthy,
            created_at=str(created_at) if created_at else None,
        )
    except Exception as e:
        logger.debug(f"Error checking project desktop: {e}")
        return None


def list_active_desktops(runtime: str | None = None) -> list[ActiveDesktopInfo]:
    """Discover all active virtual desktop containers across the host."""
    runtime_bin = runtime or "podman"
    desktops: list[ActiveDesktopInfo] = []

    try:
        proc = subprocess.run(
            [
                runtime_bin,
                "ps",
                "--filter",
                "label=pa-container.type=agent",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []

        try:
            raw_data = json.loads(proc.stdout)
            containers = raw_data if isinstance(raw_data, list) else [raw_data]
        except json.JSONDecodeError:
            containers = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]

        for c in containers:
            names = c.get("Names") or []
            if isinstance(names, str):
                names = [names]
            if not names:
                continue
            name = names[0].lstrip("/")

            labels = c.get("Labels") or {}
            if not isinstance(labels, dict):
                labels = {}

            novnc_port = query_container_port(runtime_bin, name, 6080)
            vnc_port = query_container_port(runtime_bin, name, 5900)

            # Skip agent containers that don't publish desktop ports
            if not novnc_port and not vnc_port:
                continue

            proj_hash = labels.get("pa-container.project.hash") or name.removeprefix("pa-container-agent-")
            proj_name = labels.get("pa-container.project.name") or proj_hash

            proj_path_raw = labels.get("pa-container.project.path")
            proj_path = Path(proj_path_raw) if proj_path_raw else None

            novnc_url = f"http://127.0.0.1:{novnc_port}/vnc.html?autoconnect=true&resize=scale" if novnc_port else None
            vnc_endpoint = f"127.0.0.1:{vnc_port}" if vnc_port else None
            is_healthy = check_desktop_health(novnc_url)
            created_at = c.get("Created") or c.get("CreatedAt")

            desktops.append(
                ActiveDesktopInfo(
                    project_name=proj_name,
                    project_path=proj_path,
                    project_hash=proj_hash,
                    container_name=name,
                    novnc_port=novnc_port,
                    novnc_url=novnc_url,
                    vnc_port=vnc_port,
                    vnc_endpoint=vnc_endpoint,
                    display="wayland-0",
                    is_healthy=is_healthy,
                    created_at=str(created_at) if created_at else None,
                )
            )
    except Exception as e:
        logger.debug(f"Error listing active desktops via {runtime_bin}: {e}")

    return sorted(desktops, key=lambda d: d.project_name)


@dataclass
class DesktopOptions:
    """Options for the 'desktop' subcommand."""

    verbose: bool = False
    quiet: bool = False
    log_level: str | None = None
    log_file: Path | None = None
    no_color: bool = False
    all: bool = False
    open: bool = False
    url: bool = False
    vnc: bool = False
    json: bool = False


def handle_desktop_command(options: DesktopOptions | Any) -> int:
    """Execute the 'desktop' / 'desktops' subcommand actions."""
    import os
    import webbrowser

    from rich.console import Console
    from rich.table import Table

    project_dir = Path(os.environ.get("PROJECT_DIR", Path.cwd()))
    no_color = bool(getattr(options, "no_color", False))
    opt_all = bool(getattr(options, "all", False))
    opt_open = bool(getattr(options, "open", False))
    opt_url = bool(getattr(options, "url", False))
    opt_vnc = bool(getattr(options, "vnc", False))
    opt_json = bool(getattr(options, "json", False))

    console = Console(no_color=no_color)
    is_in_project = (project_dir / ".pa-container").exists() or (project_dir / "config.yaml").exists()

    # If --all is requested, or if executed outside of any project workspace, list all active desktops
    if opt_all or not is_in_project:
        desktops = list_active_desktops()

        if opt_json:
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
            console.print(json.dumps(data, indent=2))
            return 0

        if opt_url:
            for d in desktops:
                if d.novnc_url:
                    console.print(d.novnc_url)
            return 0

        if opt_vnc:
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

        if opt_open:
            for d in desktops:
                if d.novnc_url:
                    webbrowser.open(d.novnc_url)
        return 0

    # Project-specific query
    from images import read_project_packages

    active_pkgs = read_project_packages(project_dir)
    if "virtual-desktop" not in active_pkgs:
        console.print(
            "[bold red]Error:[/bold red] The 'desktop' subcommand requires the 'virtual-desktop' capability package, but it is not enabled in .pa-container/config.yaml.\n\n"
            "To enable this capability, add 'virtual-desktop' to the 'packages:' list in your .pa-container/config.yaml:\n"
            "    packages:\n"
            "        - virtual-desktop"
        )
        return 1

    desktop_info = get_project_desktop(project_dir)

    if opt_json:
        if not desktop_info:
            console.print(json.dumps({"status": "inactive", "project": project_dir.name}))
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
        console.print(json.dumps(data_single, indent=2))
        return 0

    if opt_url:
        if desktop_info and desktop_info.novnc_url:
            console.print(desktop_info.novnc_url)
            return 0
        console.print("[red]noVNC port not published[/red]")
        return 1

    if opt_vnc:
        if desktop_info and desktop_info.vnc_endpoint:
            console.print(desktop_info.vnc_endpoint)
            return 0
        console.print("[red]VNC port not published[/red]")
        return 1

    if not desktop_info:
        console.print(f"[yellow]No active virtual desktop running for project '{project_dir.name}'.[/yellow]")
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

    if opt_open and desktop_info.novnc_url:
        webbrowser.open(desktop_info.novnc_url)

    return 0
