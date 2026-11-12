from __future__ import annotations

import sys
from typing import TypedDict

sys.dont_write_bytecode = True


class DesktopEndpointConfig(TypedDict, total=False):
    """Configuration for a virtual desktop network endpoint (VNC or noVNC)."""

    enabled: bool
    port: int | str
    expose: str


class DesktopGpuConfig(TypedDict, total=False):
    """Configuration for virtual desktop graphics acceleration."""

    enabled: bool | str


class DesktopConfig(TypedDict, total=False):
    """Headless Wayland desktop and GUI application configuration."""

    enabled: bool
    resolution: str
    compositor: str
    vnc: DesktopEndpointConfig
    novnc: DesktopEndpointConfig
    open_browser: bool
    gpu: DesktopGpuConfig
