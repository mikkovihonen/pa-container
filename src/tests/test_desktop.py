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
    import pytest

    with pytest.raises(ValueError, match="Missing required 'desktop' configuration section"):
        read_desktop_config(tmp_path)


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
    import pytest

    content = """
desktop:
  enabled: "yes"
  resolution: "invalid_resolution"
  compositor: "kde"
  open_browser: false
  vnc:
    enabled: true
    port: 999999
    expose: "world"
  novnc:
    enabled: true
    port: "not_a_number"
    expose: "localhost"
  gpu:
    enabled: "auto"
"""
    (tmp_path / "config.yaml").write_text(content)
    with pytest.raises(ValueError, match="Invalid 'desktop.enabled': expected bool"):
        read_desktop_config(tmp_path)


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
                "Names": ["pa-container-agent-test1234"],
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
        assert desktop_info.container_name == "pa-container-agent-test1234"
        assert desktop_info.novnc_port == 49152
        assert desktop_info.vnc_port == 49153
        assert "49152" in desktop_info.novnc_url
        assert desktop_info.vnc_endpoint == "127.0.0.1:49153"
        assert desktop_info.is_healthy is True


def test_get_project_desktop_names_empty_fallback(tmp_path: Path):
    proj_dir = tmp_path / "my_project"
    proj_dir.mkdir()
    ps_output = json.dumps([{"Names": [], "Created": "2026-11-07T20:00:00Z"}])
    with (
        patch("subprocess.run") as mock_run,
        patch("desktop.query_container_port", return_value=49152),
        patch("desktop.check_desktop_health", return_value=True),
        patch("project.project_key", return_value="test1234"),
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout=ps_output)
        desktop_info = get_project_desktop(proj_dir, runtime="podman")
        assert desktop_info is not None
        assert desktop_info.container_name == "pa-container-agent-test1234"


def test_list_active_desktops():
    ps_output = json.dumps(
        [
            {
                "Names": ["pa-container-agent-proj1"],
                "Labels": {
                    "pa-container.project.name": "Project1",
                    "pa-container.project.hash": "hash1",
                },
                "Created": "2026-11-07T20:00:00Z",
            },
            {
                "Names": ["pa-container-agent-proj2"],
                "Labels": {
                    "pa-container.project.name": "Project2",
                    "pa-container.project.hash": "hash2",
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


def test_agent_desktop_cli_structure():
    import os

    from config import REPO_ROOT

    agent_desktop = REPO_ROOT / "coding-agent" / "agent-desktop"
    assert agent_desktop.is_file()
    assert os.access(agent_desktop, os.X_OK)

    # Legacy pi-desktop must not exist
    PA_DESKTOP = REPO_ROOT / "coding-agent" / "pi-desktop"
    assert not PA_DESKTOP.exists()

    content = agent_desktop.read_text()
    assert "Usage: agent-desktop <command> [args...]" in content
    expected_subcommands = [
        "status",
        "screenshot",
        "windows",
        "launch",
        "move",
        "mouse-click-left",
        "mouse-click-right",
        "mouse-left-down",
        "mouse-left-up",
        "mouse-right-down",
        "mouse-right-up",
        "drag",
        "type",
        "key",
    ]
    for subcmd in expected_subcommands:
        assert f"{subcmd})" in content, f"Subcommand {subcmd} missing in agent-desktop script"

    # Key combinations handling
    assert 'send_key "$k"' in content
    assert "IFS='+' read -ra parts" in content


def test_in_container_virtual_desktop_skill():
    from config import REPO_ROOT
    from yaml_strict import load_yaml_strict

    # Root repository must NOT have .pi/skills/virtual-desktop
    host_skill = REPO_ROOT / ".pi" / "skills" / "virtual-desktop"
    assert not host_skill.exists()

    # In-container skill must exist in coding-agent/skills/virtual-desktop/SKILL.md
    container_skill = REPO_ROOT / "coding-agent" / "skills" / "virtual-desktop" / "SKILL.md"
    assert container_skill.is_file()

    content = container_skill.read_text()
    assert content.startswith("---\n")
    end_fm = content.find("\n---\n", 4)
    assert end_fm != -1
    fm_str = content[4:end_fm]
    metadata = load_yaml_strict(fm_str)
    assert isinstance(metadata, dict)
    assert metadata["name"] == "virtual-desktop"
    assert "description" in metadata

    # Pure in-container abstraction
    assert "agent-desktop" in content
    assert "pa-container desktop" not in content
    assert "pa desktop" not in content
    assert "mouse-click-left" in content
    assert "mouse-click-right" in content
    assert "drag" in content
    assert "key ctrl+s" in content


def test_containerfile_and_entrypoint_desktop_skill_integration():
    from config import REPO_ROOT
    from images import _IMAGE_DEFINITION_FILES

    # images.py tracking
    assert "agent-desktop" in _IMAGE_DEFINITION_FILES
    assert "pi-desktop" not in _IMAGE_DEFINITION_FILES

    # Containerfile COPY
    containerfile = (REPO_ROOT / "coding-agent" / "Containerfile").read_text()
    assert "COPY coding-agent/agent-desktop /usr/local/bin/agent-desktop" in containerfile
    assert "COPY coding-agent/skills /usr/local/share/pa-container/skills" in containerfile
    assert "pi-desktop" not in containerfile

    # entrypoint.sh dynamic provisioning and cleanup
    entrypoint = (REPO_ROOT / "coding-agent" / "entrypoint.sh").read_text()
    assert "/home/agent/.pi/agent/skills/virtual-desktop" in entrypoint
    assert "/usr/local/share/pa-container/skills/virtual-desktop" in entrypoint
    assert "rm -rf /home/agent/.pi/agent/skills/virtual-desktop" in entrypoint


def test_desktop_exit_prevention_and_supervisor():
    from config import REPO_ROOT
    from images import _IMAGE_DEFINITION_FILES

    # 1. Config tracking
    assert "labwc/menu.xml" in _IMAGE_DEFINITION_FILES
    assert "labwc/rc.xml" in _IMAGE_DEFINITION_FILES

    # 2. labwc menu.xml must not offer Exit or Poweroff
    menu_path = REPO_ROOT / "coding-agent" / "labwc" / "menu.xml"
    assert menu_path.is_file()
    menu_content = menu_path.read_text()
    assert '<action name="Exit"' not in menu_content
    assert "poweroff" not in menu_content.lower()

    # 3. labwc rc.xml must disable exit shortcuts
    rc_path = REPO_ROOT / "coding-agent" / "labwc" / "rc.xml"
    assert rc_path.is_file()
    rc_content = rc_path.read_text()
    assert 'key="W-F4"' in rc_content
    assert 'key="C-A-BackSpace"' in rc_content
    assert '<action name="None"' in rc_content

    # 4. Containerfile must deploy labwc config and noVNC reconnect settings
    containerfile = (REPO_ROOT / "coding-agent" / "Containerfile").read_text()
    assert "COPY coding-agent/labwc /etc/xdg/labwc" in containerfile
    assert "mandatory.json" in containerfile
    assert '"reconnect": true' in containerfile

    # 5. entrypoint.sh must seed config and run the auto-recovery supervisor loop
    entrypoint = (REPO_ROOT / "coding-agent" / "entrypoint.sh").read_text()
    assert "/etc/xdg/labwc/* /home/agent/.config/labwc/" in entrypoint
    assert 'kill -0 "$_labwc_pid"' in entrypoint
    assert 'kill -0 "$_wayvnc_pid"' in entrypoint
