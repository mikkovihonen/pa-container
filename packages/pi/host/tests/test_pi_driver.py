from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from pa_packages.pi.host.driver import PiAgentDriver
from pa_packages.pi.host.plugin import PiPlugin


def test_pi_plugin_returns_driver():
    plugin = PiPlugin(manifest=None, package_dir=Path("."), project_dir=None)  # type: ignore[arg-type]
    driver = plugin.get_agent_driver()
    assert isinstance(driver, PiAgentDriver)


def test_pi_driver_contracts(tmp_path: Path):
    driver = PiAgentDriver()
    assert driver.name == "pi"
    assert driver.required_packages == ["pi"]
    assert driver.get_command(["--foo", "bar"]) == ["--foo", "bar"]
    assert driver.get_environment() == {}
    meta = driver.get_orchestrator_metadata("t3")
    assert meta is not None
    assert meta.provider_kind == "pi"
    assert meta.instance_id == "pi"
    assert meta.settings == {"binaryPath": "pi", "launchArgs": ""}

    project_dir = tmp_path / "project"
    agent_dir = project_dir / ".pa-container" / "agents" / "pi"
    mounts = driver.get_mounts(project_dir)
    assert len(mounts) == 1
    assert mounts[0].source == agent_dir
    assert mounts[0].destination == "/home/agent/.pi/agent"
    assert mounts[0].to_run_args() == ["--volume", f"{agent_dir}:/home/agent/.pi/agent"]
    assert driver.get_shadow_paths() == ["/home/agent/.pi/agent/bin"]
    assert driver.get_sessions_dir(project_dir) == agent_dir / "sessions"

    # Synthesize config when models.json does not exist
    server_configs = [{"name": "local-qwen", "baseUrl": "http://llama:9999/v1"}]
    gateway_configs = [{"name": "opper", "baseUrl": "https://api.opper.ai"}]
    driver.synthesize_config(server_configs, gateway_configs, "local-qwen", project_dir)

    models_file = agent_dir / "models.json"
    assert models_file.is_file()
    data = json.loads(models_file.read_text())
    assert "local-qwen" in data["providers"]
    assert data["providers"]["local-qwen"]["baseUrl"] == "http://llama:9999/v1"
    assert "opper" in data["providers"]

    # When models.yaml exists, synthesize_config updates models.json
    (project_dir / ".pa-container" / "models.yaml").write_text("allow:\n  - new-model\n")
    new_servers = [{"name": "new-model", "baseUrl": "http://llama:8888/v1"}]
    driver.synthesize_config(new_servers, [], "new-model", project_dir)
    updated_data = json.loads(models_file.read_text())
    assert "new-model" in updated_data["providers"]
    assert "local-qwen" not in updated_data["providers"]
