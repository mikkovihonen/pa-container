from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from pa_packages.virtual_desktop.host.desktop import (
    ActiveDesktopInfo,
    DesktopOptions,
    check_desktop_health,
    get_project_desktop,
    handle_desktop_command,
    list_active_desktops,
    read_desktop_config,
    resolve_desktop_ports,
)
from pa_packages.virtual_desktop.host.plugin import VirtualDesktopPlugin

from util import is_port_available


def test_read_desktop_config_defaults(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("schema_version: '0.7.0'\n")
    import pytest

    with pytest.raises(ValueError, match="Missing required 'virtual-desktop' package configuration"):
        read_desktop_config(tmp_path)


def test_read_desktop_config_custom(tmp_path: Path):
    content = """
packages:
  - virtual-desktop:
      features: []
      config:
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
      secrets: []
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
packages:
  - virtual-desktop:
      features: []
      config:
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
      secrets: []
"""
    (tmp_path / "config.yaml").write_text(content)
    with pytest.raises(ValueError, match="Invalid 'virtual-desktop.enabled': expected bool"):
        read_desktop_config(tmp_path)


def test_read_desktop_config_x11_backend(tmp_path: Path):
    """The 'compositor' key is wayland-only; an x11 backend config must validate without it."""
    content = """
packages:
  - virtual-desktop:
      features:
        - x11: {config: {}, secrets: []}
      config:
        enabled: true
        resolution: "1280x1024"
        open_browser: false
        vnc:
          enabled: true
          port: "auto"
          expose: "localhost"
        novnc:
          enabled: true
          port: "auto"
          expose: "localhost"
        gpu:
          enabled: false
      secrets: []
"""
    (tmp_path / "config.yaml").write_text(content)
    cfg = read_desktop_config(tmp_path)
    assert cfg["enabled"] is True
    assert cfg["resolution"] == "1280x1024"
    # compositor defaults to labwc when omitted (valid for wayland; ignored on x11)
    assert cfg["compositor"] == "labwc"


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
        patch("pa_packages.virtual_desktop.host.desktop.query_container_port") as mock_port,
        patch("pa_packages.virtual_desktop.host.desktop.check_desktop_health", return_value=True),
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
        patch("pa_packages.virtual_desktop.host.desktop.query_container_port", return_value=49152),
        patch("pa_packages.virtual_desktop.host.desktop.check_desktop_health", return_value=True),
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
        patch("pa_packages.virtual_desktop.host.desktop.query_container_port") as mock_port,
        patch("pa_packages.virtual_desktop.host.desktop.check_desktop_health", return_value=True),
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
    with patch("pa_packages.virtual_desktop.host.desktop.is_port_available", return_value=True):
        novnc_p, vnc_p = resolve_desktop_ports(cfg_explicit)
        assert novnc_p == 6080
        assert vnc_p == 5900

    # Case 3: Busy port fallback to ephemeral
    with (
        patch("pa_packages.virtual_desktop.host.desktop.is_port_available", return_value=False),
        patch("util.get_free_port", side_effect=[60002, 50002]),
    ):
        novnc_p, vnc_p = resolve_desktop_ports(cfg_explicit)
        assert novnc_p == 60002
        assert vnc_p == 50002


def test_agent_desktop_cli_structure():
    import os

    from config import REPO_ROOT

    agent_desktop = REPO_ROOT / "pa_packages" / "virtual-desktop" / "container" / "agent-desktop"
    assert agent_desktop.is_file()
    assert os.access(agent_desktop, os.X_OK)

    # Legacy coding-agent/agent-desktop and pi-desktop must not exist
    assert not (REPO_ROOT / "coding-agent" / "agent-desktop").exists()
    assert not (REPO_ROOT / "coding-agent" / "pi-desktop").exists()

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

    # Backend awareness: exports the backend variable and reports both display backends
    assert 'PA_DESKTOP_BACKEND="${PA_DESKTOP_BACKEND:-wayland}"' in content
    assert 'if [ "${PA_DESKTOP_BACKEND}" = "x11" ]' in content
    assert "pgrep -x x11vnc" in content


def test_in_container_virtual_desktop_skill():
    from config import REPO_ROOT
    from yaml_strict import load_yaml_strict

    # Root repository must NOT have .pi/skills/virtual-desktop or coding-agent/skills
    host_skill = REPO_ROOT / ".pi" / "skills" / "virtual-desktop"
    assert not host_skill.exists()
    assert not (REPO_ROOT / "coding-agent" / "skills").exists()

    # In-container skill must exist in pa_packages/virtual-desktop/container/skill/SKILL.md
    container_skill = REPO_ROOT / "pa_packages" / "virtual-desktop" / "container" / "skill" / "SKILL.md"
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

    assert "pi-desktop" not in _IMAGE_DEFINITION_FILES
    assert "labwc/menu.xml" not in _IMAGE_DEFINITION_FILES
    assert "labwc/rc.xml" not in _IMAGE_DEFINITION_FILES

    # pa_packages/virtual-desktop owns agent-desktop deployment in container payload
    pkg_vd = REPO_ROOT / "pa_packages" / "virtual-desktop"
    assert (pkg_vd / "container" / "agent-desktop").is_file()
    assert (pkg_vd / "container" / "build.sh").is_file()
    assert "agent-desktop" in (pkg_vd / "container" / "build.sh").read_text()

    # Base Containerfile is decoupled from desktop and static skills
    containerfile = (REPO_ROOT / "coding-agent" / "Containerfile").read_text()
    assert "COPY coding-agent/skills" not in containerfile
    assert "pi-desktop" not in containerfile
    assert "WITH_DESKTOP" not in containerfile

    # entrypoint.sh has modular hook execution and no hardcoded desktop references
    entrypoint = (REPO_ROOT / "coding-agent" / "entrypoint.sh").read_text()
    assert "virtual-desktop" not in entrypoint
    assert "PA_CONTAINER_DESKTOP" not in entrypoint
    assert "entrypoint.d/root" in entrypoint
    assert "entrypoint.d/agent" in entrypoint


def test_virtual_desktop_manifest_features():
    """The package manifest must declare the wayland and x11 display backend features."""
    from config import REPO_ROOT
    from yaml_strict import load_yaml_strict

    manifest = load_yaml_strict((REPO_ROOT / "pa_packages" / "virtual-desktop" / "package.yaml").read_text())
    feats = manifest["features"]
    assert feats["required"] is True
    assert set(feats) == {"required", "wayland", "x11"}
    assert feats["wayland"]["default"] is True
    assert feats["x11"]["default"] is False
    assert feats["wayland"]["payload"]["script"] == "features/wayland/build.sh"
    assert feats["x11"]["payload"]["script"] == "features/x11/build.sh"
    assert "wayland-0" in feats["wayland"]["runtime"]["env"]["WAYLAND_DISPLAY"]
    assert "WAYLAND_DISPLAY" not in feats["x11"]["runtime"]["env"]
    assert feats["wayland"]["skill_fragment"] == "features/wayland/skill/SKILL.md"
    assert feats["x11"]["skill_fragment"] == "features/x11/skill/SKILL.md"

    pkg_dir = REPO_ROOT / "pa_packages" / "virtual-desktop"
    assert (pkg_dir / "features" / "wayland" / "build.sh").is_file()
    assert (pkg_dir / "features" / "x11" / "build.sh").is_file()

    # Feature skill fragments exist and describe their backends
    wayland_frag = (pkg_dir / "features" / "wayland" / "skill" / "SKILL.md").read_text()
    x11_frag = (pkg_dir / "features" / "x11" / "skill" / "SKILL.md").read_text()
    assert "wayland-0" in wayland_frag and "labwc" in wayland_frag
    assert "Xvfb" in x11_frag and "xdotool" in x11_frag
    # Fragments are appended below the base skill; they must not carry frontmatter
    assert not wayland_frag.startswith("---")
    assert not x11_frag.startswith("---")


def test_desktop_exit_prevention_and_supervisor():
    from config import REPO_ROOT
    from images import _IMAGE_DEFINITION_FILES

    pkg_vd = REPO_ROOT / "pa_packages" / "virtual-desktop"

    # 1. Config tracking: core does not track labwc xmls in base image definition
    assert "labwc/menu.xml" not in _IMAGE_DEFINITION_FILES
    assert "labwc/rc.xml" not in _IMAGE_DEFINITION_FILES

    # 2. labwc menu.xml must not offer Exit or Poweroff
    assert not (REPO_ROOT / "coding-agent" / "labwc").exists()
    menu_path = pkg_vd / "features" / "wayland" / "config" / "labwc" / "menu.xml"
    assert menu_path.is_file()
    menu_content = menu_path.read_text()
    assert '<action name="Exit"' not in menu_content
    assert "poweroff" not in menu_content.lower()

    # 3. labwc rc.xml must disable exit shortcuts
    rc_path = pkg_vd / "features" / "wayland" / "config" / "labwc" / "rc.xml"
    assert rc_path.is_file()
    rc_content = rc_path.read_text()
    assert 'key="W-F4"' in rc_content
    assert 'key="C-A-BackSpace"' in rc_content
    assert '<action name="None"' in rc_content

    # 4. Shared package build deploys noVNC reconnect settings; feature builds deploy their backends
    shared_build = (pkg_vd / "container" / "build.sh").read_text()
    assert "mandatory.json" in shared_build
    assert '"reconnect": true' in shared_build
    wayland_build = (pkg_vd / "features" / "wayland" / "build.sh").read_text()
    assert "labwc" in wayland_build
    assert "wayvnc" in wayland_build
    x11_build = (pkg_vd / "features" / "x11" / "build.sh").read_text()
    assert "Xvfb" in x11_build
    assert "x11vnc" in x11_build
    assert "openbox" in x11_build

    # 5. Wayland agent hook seeds compositor config and runs the auto-recovery supervisor loop
    wayland_agent_hook = (pkg_vd / "features" / "wayland" / "entrypoint.d" / "agent" / "61-desktop.sh").read_text()
    assert "/etc/xdg/labwc/* /home/agent/.config/labwc/" in wayland_agent_hook
    assert 'kill -0 "$_labwc_pid"' in wayland_agent_hook
    assert 'kill -0 "$_wayvnc_pid"' in wayland_agent_hook
    assert '${PA_DESKTOP_BACKEND}" != "wayland"' in wayland_agent_hook

    # 6. X11 agent hook supervises Xvfb, openbox, and x11vnc
    x11_agent_hook = (pkg_vd / "features" / "x11" / "entrypoint.d" / "agent" / "61-desktop.sh").read_text()
    assert 'kill -0 "$_xvfb_pid"' in x11_agent_hook
    assert 'kill -0 "$_vnc_pid"' in x11_agent_hook
    assert "openbox" in x11_agent_hook
    assert '${PA_DESKTOP_BACKEND}" != "x11"' in x11_agent_hook

    # 7. Shared agent hook serves noVNC for whichever backend is active
    shared_agent_hook = (pkg_vd / "container" / "entrypoint.d" / "agent" / "60-desktop.sh").read_text()
    assert "websockify" in shared_agent_hook
    assert "PA_DESKTOP_BACKEND" in shared_agent_hook

    # Base entrypoint must NOT contain labwc or wayvnc
    entrypoint = (REPO_ROOT / "coding-agent" / "entrypoint.sh").read_text()
    assert "labwc" not in entrypoint
    assert "wayvnc" not in entrypoint


def _make_run_context(tmp_path: Path, cfg_data: dict, features: list | None):
    from cli import RunOptions
    from packages.plugin import ContainerRunSpec, RunContext

    pa_dir = tmp_path / ".pa-container"
    pa_dir.mkdir(parents=True, exist_ok=True)
    (pa_dir / "config.yaml").write_text(
        yaml.dump({"packages": [{"virtual-desktop": {"features": features or [], "config": cfg_data, "secrets": []}}]})
    )
    spec = ContainerRunSpec()
    ctx = RunContext(
        project_dir=tmp_path,
        container_name="test-agent",
        network_name="test-net",
        proxy_url=None,
        options=RunOptions(),
        config={},  # type: ignore[arg-type]
        package_configs={"virtual-desktop": cfg_data},
    )
    return spec, ctx


def test_virtual_desktop_plugin(tmp_path: Path):
    """Legacy configs without explicit features keep the default wayland backend."""
    from config import REPO_ROOT

    cfg_data = {
        "resolution": "1280x720",
        "compositor": "labwc",
        "open_browser": False,
        "vnc": {"enabled": True, "port": "auto", "expose": "localhost"},
        "novnc": {"enabled": True, "port": "auto", "expose": "localhost"},
        "gpu": {"enabled": False},
    }
    spec, ctx = _make_run_context(tmp_path, cfg_data, features=[])
    plugin = VirtualDesktopPlugin(
        manifest=None,
        package_dir=REPO_ROOT / "pa_packages" / "virtual-desktop",  # type: ignore[arg-type]
        project_dir=tmp_path,
    )
    plugin.on_container_configure(spec, ctx)
    assert ctx.has_mode("desktop")
    assert ctx.get_attribute("desktop.backend") == "wayland"
    assert spec.env["PA_CONTAINER_DESKTOP"] == "true"
    assert spec.env["PA_DESKTOP_BACKEND"] == "wayland"
    assert spec.env["PA_DESKTOP_RESOLUTION"] == "1280x720"
    assert spec.env["WAYLAND_DISPLAY"] == "wayland-0"
    assert any(":6080" in p for p in spec.ports)
    assert any(":5900" in p for p in spec.ports)
    assert any("pa-container.desktop.enabled=true" in arg for arg in spec.extra_run_args)
    assert any("pa-container.desktop.backend=wayland" in arg for arg in spec.extra_run_args)
    # shared and wayland backend hooks are mounted
    joined = " ".join(spec.extra_run_args)
    assert "container/entrypoint.d/root/60-desktop.sh" in joined
    assert "container/entrypoint.d/agent/60-desktop.sh" in joined
    assert "features/wayland/entrypoint.d/root/61-desktop.sh" in joined
    assert "features/wayland/entrypoint.d/agent/61-desktop.sh" in joined
    assert "features/x11/" not in joined
    plugin.post_start(ctx)


def test_virtual_desktop_plugin_x11_backend(tmp_path: Path):
    """Selecting the x11 feature switches env, labels, and hook mounts to the X11 backend."""
    from config import REPO_ROOT

    cfg_data = {
        "resolution": "1600x900",
        "open_browser": False,
        "vnc": {"enabled": True, "port": "auto", "expose": "localhost"},
        "novnc": {"enabled": True, "port": "auto", "expose": "localhost"},
        "gpu": {"enabled": False},
    }
    spec, ctx = _make_run_context(tmp_path, cfg_data, features=[{"x11": {"config": {}, "secrets": []}}])
    plugin = VirtualDesktopPlugin(
        manifest=None,
        package_dir=REPO_ROOT / "pa_packages" / "virtual-desktop",  # type: ignore[arg-type]
        project_dir=tmp_path,
    )
    plugin.on_container_configure(spec, ctx)
    assert ctx.get_attribute("desktop.backend") == "x11"
    assert spec.env["PA_DESKTOP_BACKEND"] == "x11"
    assert spec.env["PA_DESKTOP_RESOLUTION"] == "1600x900"
    assert "WAYLAND_DISPLAY" not in spec.env
    assert spec.env["DISPLAY"] == ":0"
    assert any("pa-container.desktop.backend=x11" in arg for arg in spec.extra_run_args)
    joined = " ".join(spec.extra_run_args)
    assert "features/x11/entrypoint.d/root/61-desktop.sh" in joined
    assert "features/x11/entrypoint.d/agent/61-desktop.sh" in joined
    assert "features/wayland/" not in joined


def test_virtual_desktop_plugin_explicit_wayland_feature(tmp_path: Path):
    """Explicitly enabling the wayland feature behaves like the default backend."""
    from config import REPO_ROOT

    cfg_data = {
        "resolution": "1920x1080",
        "open_browser": False,
        "vnc": {"enabled": True, "port": "auto", "expose": "localhost"},
        "novnc": {"enabled": True, "port": "auto", "expose": "localhost"},
        "gpu": {"enabled": False},
    }
    spec, ctx = _make_run_context(tmp_path, cfg_data, features=[{"wayland": {"config": {}, "secrets": []}}])
    plugin = VirtualDesktopPlugin(
        manifest=None,
        package_dir=REPO_ROOT / "pa_packages" / "virtual-desktop",  # type: ignore[arg-type]
        project_dir=tmp_path,
    )
    plugin.on_container_configure(spec, ctx)
    assert spec.env["PA_DESKTOP_BACKEND"] == "wayland"
    assert spec.env["WAYLAND_DISPLAY"] == "wayland-0"


def test_virtual_desktop_plugin_mutually_exclusive_backends(tmp_path: Path):
    """Enabling both display backends must fail with a clear error."""
    import pytest

    from config import REPO_ROOT

    cfg_data = {
        "resolution": "1920x1080",
        "open_browser": False,
        "vnc": {"enabled": True, "port": "auto", "expose": "localhost"},
        "novnc": {"enabled": True, "port": "auto", "expose": "localhost"},
        "gpu": {"enabled": False},
    }
    spec, ctx = _make_run_context(
        tmp_path,
        cfg_data,
        features=[
            {"wayland": {"config": {}, "secrets": []}},
            {"x11": {"config": {}, "secrets": []}},
        ],
    )
    plugin = VirtualDesktopPlugin(
        manifest=None,
        package_dir=REPO_ROOT / "pa_packages" / "virtual-desktop",  # type: ignore[arg-type]
        project_dir=tmp_path,
    )
    with pytest.raises(ValueError, match="mutually exclusive"):
        plugin.on_container_configure(spec, ctx)


def test_virtual_desktop_plugin_unknown_feature(tmp_path: Path):
    """An unknown backend feature must fail with a clear error."""
    import pytest

    from config import REPO_ROOT

    cfg_data = {
        "resolution": "1920x1080",
        "open_browser": False,
        "vnc": {"enabled": True, "port": "auto", "expose": "localhost"},
        "novnc": {"enabled": True, "port": "auto", "expose": "localhost"},
        "gpu": {"enabled": False},
    }
    spec, ctx = _make_run_context(tmp_path, cfg_data, features=[{"mir": {"config": {}, "secrets": []}}])
    plugin = VirtualDesktopPlugin(
        manifest=None,
        package_dir=REPO_ROOT / "pa_packages" / "virtual-desktop",  # type: ignore[arg-type]
        project_dir=tmp_path,
    )
    with pytest.raises(ValueError, match="unknown display backend feature"):
        plugin.on_container_configure(spec, ctx)


def test_virtual_desktop_gpu_passthrough(tmp_path: Path):
    from cli import RunOptions
    from packages.plugin import ContainerRunSpec, RunContext

    pa_dir = tmp_path / ".pa-container"
    pa_dir.mkdir(parents=True)
    cfg_data = {
        "resolution": "1920x1080",
        "compositor": "labwc",
        "open_browser": False,
        "vnc": {"enabled": True, "port": "auto", "expose": "localhost"},
        "novnc": {"enabled": True, "port": "auto", "expose": "localhost"},
        "gpu": {"enabled": "auto"},
    }
    (pa_dir / "config.yaml").write_text(
        yaml.dump({"packages": [{"virtual-desktop": {"features": [], "config": cfg_data, "secrets": []}}]})
    )
    plugin = VirtualDesktopPlugin(manifest=None, package_dir=Path("."), project_dir=tmp_path)  # type: ignore[arg-type]
    spec = ContainerRunSpec()
    ctx = RunContext(
        project_dir=tmp_path,
        container_name="test-agent",
        network_name="test-net",
        proxy_url=None,
        options=RunOptions(),
        config={},  # type: ignore[arg-type]
        package_configs={"virtual-desktop": cfg_data},
    )

    with patch("pathlib.Path.exists", return_value=True):
        plugin.on_container_configure(spec, ctx)
        assert "/dev/dri" in spec.devices
        assert "--group-add" in spec.extra_run_args
        assert "keep-groups" in spec.extra_run_args


class TestDesktopCli:
    def test_desktop_command_missing_package_error(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        cfg_dir = tmp_path / ".pa-container"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text("packages: ['python']\n")
        with patch("rich.console.Console.print") as mock_print:
            code = handle_desktop_command(DesktopOptions())
            assert code == 1
            output = "".join(str(call) for call in mock_print.call_args_list)
            assert "The 'desktop' subcommand requires the 'virtual-desktop' capability package" in output

    def test_desktop_active_project(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        cfg_dir = tmp_path / ".pa-container"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text("packages: ['virtual-desktop']\n")
        fake_desktop = ActiveDesktopInfo(
            project_name=tmp_path.name,
            project_path=tmp_path,
            project_hash="abc1234567",
            container_name="pa-container-agent-abc1234567",
            novnc_port=6080,
            novnc_url="http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale",
            vnc_port=5900,
            vnc_endpoint="127.0.0.1:5900",
            display=":0",
            is_healthy=True,
            created_at="2026-11-07T10:00:00Z",
        )
        with (
            patch("pa_packages.virtual_desktop.host.desktop.get_project_desktop", return_value=fake_desktop),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_desktop_command(DesktopOptions())
            assert code == 0
            output = "".join(str(call) for call in mock_print.call_args_list)
            assert "http://127.0.0.1:6080" in output
            assert "127.0.0.1:5900" in output
            assert "Healthy" in output

    def test_desktop_inactive_project(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        cfg_dir = tmp_path / ".pa-container"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text("packages: ['virtual-desktop']\n")
        with (
            patch("pa_packages.virtual_desktop.host.desktop.get_project_desktop", return_value=None),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_desktop_command(DesktopOptions())
            assert code == 1
            output = "".join(str(call) for call in mock_print.call_args_list)
            assert "No active virtual desktop running" in output

    def test_desktop_url_flag(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        cfg_dir = tmp_path / ".pa-container"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text("packages: ['virtual-desktop']\n")
        fake_desktop = ActiveDesktopInfo(
            project_name=tmp_path.name,
            project_path=tmp_path,
            project_hash="abc1234567",
            container_name="pa-container-agent-abc1234567",
            novnc_port=6080,
            novnc_url="http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale",
            vnc_port=5900,
            vnc_endpoint="127.0.0.1:5900",
            display=":0",
            is_healthy=True,
            created_at="2026-11-07T10:00:00Z",
        )
        with (
            patch("pa_packages.virtual_desktop.host.desktop.get_project_desktop", return_value=fake_desktop),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_desktop_command(DesktopOptions(url=True))
            assert code == 0
            mock_print.assert_called_once_with("http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale")

    def test_desktop_vnc_flag(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        cfg_dir = tmp_path / ".pa-container"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text("packages: ['virtual-desktop']\n")
        fake_desktop = ActiveDesktopInfo(
            project_name=tmp_path.name,
            project_path=tmp_path,
            project_hash="abc1234567",
            container_name="pa-container-agent-abc1234567",
            novnc_port=6080,
            novnc_url="http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale",
            vnc_port=5900,
            vnc_endpoint="127.0.0.1:5900",
            display=":0",
            is_healthy=True,
            created_at="2026-11-07T10:00:00Z",
        )
        with (
            patch("pa_packages.virtual_desktop.host.desktop.get_project_desktop", return_value=fake_desktop),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_desktop_command(DesktopOptions(vnc=True))
            assert code == 0
            mock_print.assert_called_once_with("127.0.0.1:5900")

    def test_desktop_json_flag(self, tmp_path: Path, monkeypatch) -> None:
        import json as json_mod

        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        cfg_dir = tmp_path / ".pa-container"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text("packages: ['virtual-desktop']\n")
        fake_desktop = ActiveDesktopInfo(
            project_name=tmp_path.name,
            project_path=tmp_path,
            project_hash="abc1234567",
            container_name="pa-container-agent-abc1234567",
            novnc_port=6080,
            novnc_url="http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale",
            vnc_port=5900,
            vnc_endpoint="127.0.0.1:5900",
            display=":0",
            is_healthy=True,
            created_at="2026-11-07T10:00:00Z",
        )
        with (
            patch("pa_packages.virtual_desktop.host.desktop.get_project_desktop", return_value=fake_desktop),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_desktop_command(DesktopOptions(json=True))
            assert code == 0
            raw_json = mock_print.call_args[0][0]
            data = json_mod.loads(raw_json)
            assert data["status"] == "running"
            assert data["novnc_port"] == 6080
            assert data["vnc_port"] == 5900

    def test_desktop_open_flag(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        cfg_dir = tmp_path / ".pa-container"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text("packages: ['virtual-desktop']\n")
        fake_desktop = ActiveDesktopInfo(
            project_name=tmp_path.name,
            project_path=tmp_path,
            project_hash="abc1234567",
            container_name="pa-container-agent-abc1234567",
            novnc_port=6080,
            novnc_url="http://127.0.0.1:6080/vnc.html?autoconnect=true&resize=scale",
            vnc_port=5900,
            vnc_endpoint="127.0.0.1:5900",
            display=":0",
            is_healthy=True,
            created_at="2026-11-07T10:00:00Z",
        )
        with (
            patch("pa_packages.virtual_desktop.host.desktop.get_project_desktop", return_value=fake_desktop),
            patch("webbrowser.open") as mock_open,
            patch("rich.console.Console.print"),
        ):
            code = handle_desktop_command(DesktopOptions(open=True))
            assert code == 0
            mock_open.assert_called_once_with(fake_desktop.novnc_url)

    def test_desktop_all_empty(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        with (
            patch("pa_packages.virtual_desktop.host.desktop.list_active_desktops", return_value=[]),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_desktop_command(DesktopOptions(all=True))
            assert code == 0
            output = "".join(str(call) for call in mock_print.call_args_list)
            assert "[dim]No active pa-container virtual desktops found on this system.[/dim]" in output

    def test_desktop_all_with_desktops(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
        desktops = [
            ActiveDesktopInfo(
                project_name="d1",
                project_path=Path("/tmp/d1"),
                project_hash="1111111111",
                container_name="pa-container-agent-1111111111",
                novnc_port=6080,
                novnc_url="http://127.0.0.1:6080",
                vnc_port=5900,
                vnc_endpoint="127.0.0.1:5900",
                display=":0",
                is_healthy=True,
                created_at="2026-11-07T10:00:00Z",
            ),
            ActiveDesktopInfo(
                project_name="d2",
                project_path=Path("/tmp/d2"),
                project_hash="2222222222",
                container_name="pa-container-agent-2222222222",
                novnc_port=6081,
                novnc_url="http://127.0.0.1:6081",
                vnc_port=5901,
                vnc_endpoint="127.0.0.1:5901",
                display=":0",
                is_healthy=False,
                created_at="2026-11-07T11:00:00Z",
            ),
        ]
        with (
            patch("pa_packages.virtual_desktop.host.desktop.list_active_desktops", return_value=desktops),
            patch("rich.console.Console.print") as mock_print,
        ):
            code = handle_desktop_command(DesktopOptions(all=True))
            assert code == 0
            assert mock_print.called
