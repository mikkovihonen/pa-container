from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from pa_packages.claude_code.host.driver import ClaudeDriver
from pa_packages.claude_code.host.plugin import ClaudePlugin


def test_claude_plugin_returns_driver():
    plugin = ClaudePlugin(manifest=None, package_dir=Path("."), project_dir=None)  # type: ignore[arg-type]
    driver = plugin.get_agent_driver()
    assert isinstance(driver, ClaudeDriver)


def test_claude_driver_contracts(tmp_path: Path):
    driver = ClaudeDriver()
    assert driver.name == "claude"
    assert driver.required_packages == ["claude-code"]
    assert driver.get_command(["-p", "hello"]) == ["-p", "hello"]
    env = driver.get_environment()
    assert env["ANTHROPIC_API_KEY"] == "ANTHROPIC_API_KEY_PLACEHOLDER"
    assert env["CLAUDE_CONFIG_DIR"] == "/home/agent/.claude"
    meta = driver.get_t3_metadata()
    assert meta is not None
    assert meta.driver_kind == "claudeAgent"
    assert meta.instance_id == "claudeAgent"
    assert meta.settings == {
        "binaryPath": "claude",
        "homePath": "/home/agent/.claude",
        "launchArgs": "",
    }

    project_dir = tmp_path / "project"
    mounts = driver.get_mounts(project_dir)
    assert len(mounts) == 1
    assert mounts[0].destination == "/home/agent/.claude"

    server_configs = [{"name": "local-claude", "baseUrl": "http://llama:9999/v1"}]
    # 1. Local server configs without Anthropic gateway: baseUrl must not point to llama-server
    driver.synthesize_config(server_configs, [], "local-qwen", project_dir)

    cfg_file = project_dir / ".pa-container" / "agents" / "claude" / "claude.json"
    assert cfg_file.is_file()
    cfg_data = json.loads(cfg_file.read_text())
    assert cfg_data["model"] == "claude-sonnet-5-5"
    assert "baseUrl" not in cfg_data

    settings_file = project_dir / ".pa-container" / "agents" / "claude" / "settings.json"
    assert settings_file.is_file()
    settings_data = json.loads(settings_file.read_text())
    assert settings_data["model"] == "claude-sonnet-5-5"
    assert "env" not in settings_data

    # 2. Custom Anthropic gateway: baseUrl trailing /v1 stripped and passed to ANTHROPIC_BASE_URL
    custom_gw = [{"name": "anthropic", "baseUrl": "http://my-proxy:8080/v1"}]
    driver.synthesize_config(server_configs, custom_gw, "claude-3-7-sonnet", project_dir)
    cfg_data = json.loads(cfg_file.read_text())
    assert cfg_data["model"] == "claude-3-7-sonnet"
    assert cfg_data["baseUrl"] == "http://my-proxy:8080"
    settings_data = json.loads(settings_file.read_text())
    assert settings_data["model"] == "claude-3-7-sonnet"
    assert settings_data["env"]["ANTHROPIC_BASE_URL"] == "http://my-proxy:8080"

    # 3. Standard public Anthropic endpoint: baseUrl omitted
    std_gw = [{"name": "anthropic", "baseUrl": "https://api.anthropic.com/v1"}]
    driver.synthesize_config(server_configs, std_gw, "claude-3-7-sonnet", project_dir)
    cfg_data = json.loads(cfg_file.read_text())
    assert cfg_data["model"] == "claude-3-7-sonnet"
    assert "baseUrl" not in cfg_data
    settings_data = json.loads(settings_file.read_text())
    assert "env" not in settings_data

    # Agent-native vs API-key environment checks
    api_gw = [
        {
            "name": "anthropic",
            "gatewayDef": type(
                "GW", (), {"gateway_type": "anthropic", "id": "anthropic", "auth": type("A", (), {"type": "api-key"})()}
            )(),
        }
    ]
    native_gw = [
        {
            "name": "anthropic-account",
            "gatewayDef": type(
                "GW",
                (),
                {
                    "gateway_type": "anthropic",
                    "id": "anthropic-account",
                    "auth": type("A", (), {"type": "agent-native"})(),
                },
            )(),
        }
    ]
    assert driver.get_environment(gateway_configs=api_gw)["ANTHROPIC_API_KEY"] == "ANTHROPIC_API_KEY_PLACEHOLDER"
    native_env = driver.get_environment(gateway_configs=native_gw)
    assert "ANTHROPIC_API_KEY" not in native_env
    assert native_env["CLAUDE_CONFIG_DIR"] == "/home/agent/.claude"

    # Pass-through of CLAUDE_CODE_OAUTH_TOKEN in agent-native mode
    token_env = driver.get_environment(
        config={"env": {"CLAUDE_CODE_OAUTH_TOKEN": "my-setup-token"}}, gateway_configs=native_gw
    )
    assert token_env.get("CLAUDE_CODE_OAUTH_TOKEN") == "my-setup-token"
