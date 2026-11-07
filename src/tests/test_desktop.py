from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

from desktop import (
    check_desktop_health,
    get_project_desktop,
    is_port_available,
    list_active_desktops,
    read_desktop_config,
    resolve_desktop_ports,
)


def test_read_desktop_config_defaults(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("schema_version: '0.6.6'\n")
    cfg = read_desktop_config(tmp_path)
    assert cfg["enabled"] is False
    assert cfg["resolution"] == "1920x1080"
    assert cfg["compositor"] == "labwc"
    assert cfg["open_browser"] is False
    assert cfg["vnc"]["enabled"] is True
    assert cfg["vnc"]["port"] == "auto"
    assert cfg["vnc"]["expose"] == "localhost"
    assert cfg["novnc"]["enabled"] is True
    assert cfg["novnc"]["port"] == "auto"
    assert cfg["novnc"]["expose"] == "localhost"
    assert cfg["gpu"]["enabled"] == "auto"


def test_read_desktop_config_custom(tmp_path: Path):
    content = """
desktop:
  enabled: true
  resolution: "2560x1440"
  compositor: "labwc"
  open_browser: true
  vnc:
    enabled: true
    port: 5901
    expose: "lan"
  novnc:
    enabled: true
    port: 6081
    expose: "lan"
  gpu:
    enabled: false
"""
    (tmp_path / "config.yaml").write_text(content)
    cfg = read_desktop_config(tmp_path)
    assert cfg["enabled"] is True
    assert cfg["resolution"] == "2560x1440"
    assert cfg["compositor"] == "labwc"
    assert cfg["open_browser"] is True
    assert cfg["vnc"]["port"] == 5901
    assert cfg["vnc"]["expose"] == "lan"
    assert cfg["novnc"]["port"] == 6081
    assert cfg["novnc"]["expose"] == "lan"
    assert cfg["gpu"]["enabled"] is False


def test_read_desktop_config_sanitization(tmp_path: Path):
    content = """
desktop:
  enabled: "yes"
  resolution: "invalid_resolution"
  compositor: "kde"
  vnc:
    port: 999999
    expose: "world"
  novnc:
    port: "not_a_number"
  gpu:
    enabled: "auto"
"""
    (tmp_path / "config.yaml").write_text(content)
    cfg = read_desktop_config(tmp_path)
    assert cfg["enabled"] is True
    assert cfg["resolution"] == "1920x1080"
    assert cfg["compositor"] == "labwc"
    assert cfg["vnc"]["port"] == "auto"
    assert cfg["vnc"]["expose"] == "localhost"
    assert cfg["novnc"]["port"] == "auto"
    assert cfg["gpu"]["enabled"] == "auto"


def test_check_desktop_health():
    with patch("urllib.request.urlopen") as mock_url:
        mock_url.return_value = MagicMock()
        assert check_desktop_health("http://127.0.0.1:6080") is True

    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        assert check_desktop_health("http://127.0.0.1:6080") is False

    assert check_desktop_health(None) is False


def test_get_project_desktop(tmp_path: Path):
    proj_dir = tmp_path / "my_project"
    proj_dir.mkdir()

    ps_output = json.dumps(
        [
            {
                "Names": ["pi-agent-test1234"],
                "Created": "2026-11-07T20:00:00Z",
            }
        ]
    )

    with (
        patch("subprocess.run") as mock_run,
        patch("desktop.query_container_port") as mock_port,
        patch("desktop.check_desktop_health", return_value=True),
        patch("project.project_key", return_value="test1234"),
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout=ps_output)

        def port_side_effect(runtime, name, target_port):
            if target_port == 6080:
                return 49152
            if target_port == 5900:
                return 49153
            return None

        mock_port.side_effect = port_side_effect

        desktop_info = get_project_desktop(proj_dir, runtime="podman")
        assert desktop_info is not None
        assert desktop_info.project_name == "my_project"
        assert desktop_info.container_name == "pi-agent-test1234"
        assert desktop_info.novnc_port == 49152
        assert desktop_info.vnc_port == 49153
        assert "49152" in desktop_info.novnc_url
        assert desktop_info.vnc_endpoint == "127.0.0.1:49153"
        assert desktop_info.is_healthy is True


def test_list_active_desktops():
    ps_output = json.dumps(
        [
            {
                "Names": ["pi-agent-proj1"],
                "Labels": {
                    "pi-container.project.name": "Project1",
                    "pi-container.project.hash": "hash1",
                },
                "Created": "2026-11-07T20:00:00Z",
            },
            {
                "Names": ["pi-agent-proj2"],
                "Labels": {
                    "pi-container.project.name": "Project2",
                    "pi-container.project.hash": "hash2",
                },
                "Created": "2026-11-07T20:05:00Z",
            },
        ]
    )

    with (
        patch("subprocess.run") as mock_run,
        patch("desktop.query_container_port") as mock_port,
        patch("desktop.check_desktop_health", return_value=True),
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout=ps_output)

        def port_side_effect(runtime, name, target_port):
            if "proj1" in name:
                return 49152 if target_port == 6080 else 49153
            if "proj2" in name:
                return 49154 if target_port == 6080 else 49155
            return None

        mock_port.side_effect = port_side_effect

        desktops = list_active_desktops(runtime="podman")
        assert len(desktops) == 2
        assert desktops[0].project_name == "Project1"
        assert desktops[0].novnc_port == 49152
        assert desktops[1].project_name == "Project2"
        assert desktops[1].novnc_port == 49154


def test_is_port_available():
    import socket

    # An unbound ephemeral port should be available
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    # After closing, it's available
    assert is_port_available(port) is True

    # When actively listening, it's not available
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))
        s.listen(1)
        assert is_port_available(port) is False


def test_resolve_desktop_ports():
    # Case 1: "auto" ports
    cfg_auto = {
        "enabled": True,
        "novnc": {"port": "auto"},
        "vnc": {"port": "auto"},
    }
    with patch("util.get_free_port", side_effect=[60001, 50001]):
        novnc_p, vnc_p = resolve_desktop_ports(cfg_auto)
        assert novnc_p == 60001
        assert vnc_p == 50001

    # Case 2: Configured available ports
    cfg_explicit = {
        "enabled": True,
        "novnc": {"port": 6080},
        "vnc": {"port": 5900},
    }
    with patch("desktop.is_port_available", return_value=True):
        novnc_p, vnc_p = resolve_desktop_ports(cfg_explicit)
        assert novnc_p == 6080
        assert vnc_p == 5900

    # Case 3: Busy port fallback to ephemeral
    with (
        patch("desktop.is_port_available", return_value=False),
        patch("util.get_free_port", side_effect=[60002, 50002]),
    ):
        novnc_p, vnc_p = resolve_desktop_ports(cfg_explicit)
        assert novnc_p == 60002
        assert vnc_p == 50002
