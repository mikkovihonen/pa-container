from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from pa_packages.antigravity.host.driver import AntigravityDriver
from pa_packages.antigravity.host.plugin import AntigravityPlugin


def test_antigravity_plugin_returns_driver():
    plugin = AntigravityPlugin(manifest=None, package_dir=Path("."), project_dir=None)  # type: ignore[arg-type]
    driver = plugin.get_agent_driver()
    assert isinstance(driver, AntigravityDriver)


def test_antigravity_driver_contracts(tmp_path: Path):
    driver = AntigravityDriver()
    assert driver.name == "antigravity"
    assert driver.required_packages == ["antigravity"]
    assert driver.get_command(["--goal", "audit"]) == ["--goal", "audit"]
    assert driver.get_environment()["GEMINI_API_KEY"] == "GEMINI_API_KEY_PLACEHOLDER"
    meta = driver.get_orchestrator_metadata("t3")
    assert meta is not None
    assert meta.provider_kind == "antigravity"
    assert meta.instance_id == "antigravity"
    assert meta.settings == {"authMethod": "oauth-personal"}

    project_dir = tmp_path / "project"
    mounts = driver.get_mounts(project_dir)
    assert len(mounts) == 3
    assert mounts[0].destination == "/home/agent/.gemini/antigravity"
    assert mounts[1].destination == "/home/agent/.gemini/antigravity-cli"
    assert mounts[2].destination == "/home/agent/.gemini/config"

    server_configs = [{"name": "local-model", "baseUrl": "http://llama:9999/v1"}]
    # 1. Local server configs without Gemini gateway: model defaults to gemini-2.5-pro, no baseUrl
    driver.synthesize_config(server_configs, [], "local-model", project_dir)

    settings_file = project_dir / ".pa-container" / "agents" / "antigravity" / "settings.json"
    assert settings_file.is_file()
    settings_data = json.loads(settings_file.read_text())
    assert settings_data["model"] == "gemini-2.5-pro"
    assert "baseUrl" not in settings_data
    assert "env" not in settings_data

    cfg_file = project_dir / ".pa-container" / "agents" / "antigravity" / "config.json"
    assert cfg_file.is_file()
    cfg_data = json.loads(cfg_file.read_text())
    assert cfg_data["model"] == "gemini-2.5-pro"
    assert cfg_data["defaultModel"] == "gemini-2.5-pro"
    assert cfg_data["models"] == []

    # 2. Custom Gemini gateway: baseUrl passed to settings and config
    custom_gw = [{"name": "gemini", "baseUrl": "http://my-proxy:8080"}]
    driver.synthesize_config(server_configs, custom_gw, "gemini-2.5-flash", project_dir)
    settings_data = json.loads(settings_file.read_text())
    assert settings_data["model"] == "gemini-2.5-flash"
    assert settings_data["baseUrl"] == "http://my-proxy:8080"
    assert settings_data["env"]["GOOGLE_GEMINI_BASE_URL"] == "http://my-proxy:8080"
    assert driver.get_environment(gateway_configs=custom_gw)["GOOGLE_GEMINI_BASE_URL"] == "http://my-proxy:8080"

    cfg_data = json.loads(cfg_file.read_text())
    assert cfg_data["model"] == "gemini-2.5-flash"
    assert cfg_data["defaultModel"] == "gemini-2.5-flash"
    assert cfg_data["baseUrl"] == "http://my-proxy:8080"
    assert cfg_data["models"] == [{"name": "gemini", "endpoint": "http://my-proxy:8080", "type": "gateway"}]

    # 3. Standard public Gemini endpoint: baseUrl omitted
    std_gw = [{"name": "google-account", "baseUrl": "https://generativelanguage.googleapis.com"}]
    driver.synthesize_config(server_configs, std_gw, "gemini-2.5-pro", project_dir)
    settings_data = json.loads(settings_file.read_text())
    assert settings_data["model"] == "gemini-2.5-pro"
    assert "baseUrl" not in settings_data
    assert "env" not in settings_data

    cfg_data = json.loads(cfg_file.read_text())
    assert cfg_data["model"] == "gemini-2.5-pro"
    assert cfg_data["defaultModel"] == "gemini-2.5-pro"
    assert "baseUrl" not in cfg_data
    assert cfg_data["models"] == [
        {"name": "google-account", "endpoint": "https://generativelanguage.googleapis.com", "type": "gateway"}
    ]

    # Agent-native vs API-key environment checks
    api_gw = [
        {
            "name": "gemini",
            "gatewayDef": type(
                "GW", (), {"gateway_type": "gemini", "id": "gemini", "auth": type("A", (), {"type": "api-key"})()}
            )(),
        }
    ]
    native_gw = [
        {
            "name": "google-account",
            "gatewayDef": type(
                "GW",
                (),
                {"gateway_type": "gemini", "id": "google-account", "auth": type("A", (), {"type": "agent-native"})()},
            )(),
        }
    ]
    assert driver.get_environment(gateway_configs=api_gw)["GEMINI_API_KEY"] == "GEMINI_API_KEY_PLACEHOLDER"
    assert "GEMINI_API_KEY" not in driver.get_environment(gateway_configs=native_gw)
