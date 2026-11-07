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
    from config_types import DesktopConfig

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from network import load_project_config, query_container_port

logger = get_category_logger(__name__, LogCategory.DESKTOP)

_DEFAULT_DESKTOP: DesktopConfig = {
    "enabled": False,
    "resolution": "1920x1080",
    "compositor": "labwc",
    "vnc": {
        "enabled": True,
        "port": "auto",
        "expose": "localhost",
    },
    "novnc": {
        "enabled": True,
        "port": "auto",
        "expose": "localhost",
    },
    "open_browser": False,
    "gpu": {
        "enabled": "auto",
    },
}


def read_desktop_config(config_dir: Path | None = None) -> DesktopConfig:
    """Read and sanitize the desktop configuration from project config.yaml."""
    cfg = load_project_config(config_dir)
    section: dict[str, Any] = cfg.get("desktop") or {}

    raw_enabled = section.get("enabled", _DEFAULT_DESKTOP["enabled"])
    if isinstance(raw_enabled, str):
        enabled = raw_enabled.strip().lower() in ("true", "1", "yes", "on")
    else:
        enabled = bool(raw_enabled)

    resolution = str(section.get("resolution", _DEFAULT_DESKTOP["resolution"])).strip()
    if not re.match(r"^\d+x\d+$", resolution):
        resolution = "1920x1080"

    compositor = str(section.get("compositor", _DEFAULT_DESKTOP["compositor"])).strip().lower()
    if compositor not in ("labwc",):
        compositor = "labwc"

    raw_open_browser = section.get("open_browser", _DEFAULT_DESKTOP["open_browser"])
    if isinstance(raw_open_browser, str):
        open_browser = raw_open_browser.strip().lower() in ("true", "1", "yes", "on")
    else:
        open_browser = bool(raw_open_browser)

    # VNC endpoint settings
    vnc_sec = section.get("vnc")
    raw_vnc: dict[str, Any] = vnc_sec if isinstance(vnc_sec, dict) else {}
    raw_vnc_enabled = raw_vnc.get("enabled", True)
    vnc_enabled = (
        raw_vnc_enabled.strip().lower() in ("true", "1", "yes", "on")
        if isinstance(raw_vnc_enabled, str)
        else bool(raw_vnc_enabled)
    )
    raw_vnc_port = raw_vnc.get("port", "auto")
    vnc_port: int | str = "auto"
    if isinstance(raw_vnc_port, int) and 1 <= raw_vnc_port <= 65535:
        vnc_port = raw_vnc_port
    elif isinstance(raw_vnc_port, str) and raw_vnc_port.isdigit() and 1 <= int(raw_vnc_port) <= 65535:
        vnc_port = int(raw_vnc_port)

    vnc_expose = str(raw_vnc.get("expose", "localhost")).strip().lower()
    if vnc_expose not in ("localhost", "lan"):
        vnc_expose = "localhost"

    # noVNC endpoint settings
    novnc_sec = section.get("novnc")
    raw_novnc: dict[str, Any] = novnc_sec if isinstance(novnc_sec, dict) else {}
    raw_novnc_enabled = raw_novnc.get("enabled", True)
    novnc_enabled = (
        raw_novnc_enabled.strip().lower() in ("true", "1", "yes", "on")
        if isinstance(raw_novnc_enabled, str)
        else bool(raw_novnc_enabled)
    )
    raw_novnc_port = raw_novnc.get("port", "auto")
    novnc_port: int | str = "auto"
    if isinstance(raw_novnc_port, int) and 1 <= raw_novnc_port <= 65535:
        novnc_port = raw_novnc_port
    elif isinstance(raw_novnc_port, str) and raw_novnc_port.isdigit() and 1 <= int(raw_novnc_port) <= 65535:
        novnc_port = int(raw_novnc_port)

    novnc_expose = str(raw_novnc.get("expose", "localhost")).strip().lower()
    if novnc_expose not in ("localhost", "lan"):
        novnc_expose = "localhost"

    # GPU settings
    gpu_sec = section.get("gpu")
    raw_gpu: dict[str, Any] = gpu_sec if isinstance(gpu_sec, dict) else {}
    raw_gpu_enabled = raw_gpu.get("enabled", "auto")
    if isinstance(raw_gpu_enabled, str):
        val = raw_gpu_enabled.strip().lower()
        gpu_enabled: bool | str = val in ("true", "1", "yes", "on") if val != "auto" else "auto"
    else:
        gpu_enabled = bool(raw_gpu_enabled)

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


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is available on the given host interface."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


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
    except Exception:
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
        container_name = names[0].lstrip("/") if names else f"pi-agent-{proj_hash}"

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
