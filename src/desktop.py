from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config_types import DesktopConfig

sys.dont_write_bytecode = True

from logging_driver import LogCategory, get_category_logger
from network import load_project_config, query_container_port

logger = get_category_logger(__name__, LogCategory.DESKTOP)


def read_desktop_config(config_dir: Path | None = None) -> DesktopConfig:
    """Read and validate the desktop configuration from project config.yaml."""
    cfg = load_project_config(config_dir)
    section = cfg.get("desktop")
    if not isinstance(section, dict):
        raise ValueError("Missing required 'desktop' configuration section in project config")

    for key in ("enabled", "resolution", "compositor", "vnc", "novnc", "open_browser", "gpu"):
        if key not in section:
            raise ValueError(f"Missing required 'desktop.{key}' configuration in project config")

    enabled = section["enabled"]
    if not isinstance(enabled, bool):
        raise ValueError(f"Invalid 'desktop.enabled': expected bool, got {type(enabled).__name__}")

    resolution = str(section["resolution"]).strip()
    if not re.match(r"^\d+x\d+$", resolution):
        raise ValueError(f"Invalid 'desktop.resolution': expected WIDTHxHEIGHT format, got {resolution!r}")

    compositor = str(section["compositor"]).strip().lower()
    if compositor not in ("labwc",):
        raise ValueError(f"Invalid 'desktop.compositor': unsupported compositor {compositor!r}")

    open_browser = section["open_browser"]
    if not isinstance(open_browser, bool):
        raise ValueError(f"Invalid 'desktop.open_browser': expected bool, got {type(open_browser).__name__}")

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
