from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from pa_packages.opencode.host.driver import OpenCodeDriver
from pa_packages.opencode.host.plugin import OpenCodePlugin


def test_opencode_plugin_returns_driver():
    plugin = OpenCodePlugin(manifest=None, package_dir=Path("."), project_dir=None)  # type: ignore[arg-type]
    driver = plugin.get_agent_driver()
    assert isinstance(driver, OpenCodeDriver)


def test_opencode_driver_contracts(tmp_path: Path):
    driver = OpenCodeDriver()
    assert driver.name == "opencode"
    assert driver.required_packages == ["opencode"]
    assert driver.get_command(["run", "main.py"]) == ["run", "main.py"]
    assert driver.get_environment() == {}
    meta = driver.get_t3_metadata()
    assert meta is not None
    assert meta.driver_kind == "opencode"
    assert meta.instance_id == "opencode"
    assert meta.settings == {"binaryPath": "opencode", "serverUrl": "", "serverPassword": ""}

    project_dir = tmp_path / "project"
    mounts = driver.get_mounts(project_dir)
    assert len(mounts) == 2
    assert mounts[0].destination == "/home/agent/.config/opencode"
    assert mounts[1].destination == "/home/agent/.local/share/opencode"
    assert driver.get_sessions_dir(project_dir) == project_dir / ".pa-container" / "agents" / "opencode" / "data"

    legacy_file = project_dir / ".pa-container" / "agents" / "opencode" / "config.json"
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_text("{}")

    server_configs = [{"name": "qwen", "baseUrl": "http://llama:9999/v1"}]
    gateway_configs = [{"name": "opper", "baseUrl": "https://api.opper.ai", "containerEnvVar": "OPPER_API_KEY"}]
    driver.synthesize_config(server_configs, gateway_configs, "qwen", project_dir)

    assert legacy_file.exists()
    cfg_file = project_dir / ".pa-container" / "agents" / "opencode" / "opencode.json"
    assert cfg_file.is_file()
    cfg_data = json.loads(cfg_file.read_text())
    assert cfg_data["$schema"] == "https://opencode.ai/config.json"
    assert cfg_data["model"] == "qwen/qwen"
    assert cfg_data["enabled_providers"] == ["qwen", "opper"]
    assert "qwen" in cfg_data["providers"]
    assert cfg_data["providers"]["qwen"]["settings"]["baseURL"] == "http://llama:9999/v1"
    assert cfg_data["providers"]["qwen"]["package"] == "@opencode/ai/providers/openai-compatible"
    assert cfg_data["providers"]["qwen"]["models"]["qwen"]["name"] == "qwen"
    assert "opper" in cfg_data["providers"]
    assert cfg_data["providers"]["opper"]["settings"]["baseURL"] == "https://api.opper.ai"
    assert cfg_data["providers"]["opper"]["package"] == "@opencode/ai/providers/openai-compatible"
    assert cfg_data["providers"]["opper"]["models"]["opper"]["name"] == "opper"
    assert cfg_data["providers"]["opper"]["env"] == ["OPPER_API_KEY"]
