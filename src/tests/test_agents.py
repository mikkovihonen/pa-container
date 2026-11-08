from __future__ import annotations

import json

import pytest

from agents import (
    AVAILABLE_AGENTS,
    AntigravityDriver,
    ClaudeDriver,
    OpenCodeDriver,
    PiAgentDriver,
    get_agent_driver,
)


def test_available_agents():
    assert "pi" in AVAILABLE_AGENTS
    assert "opencode" in AVAILABLE_AGENTS
    assert "antigravity" in AVAILABLE_AGENTS
    assert "claude" in AVAILABLE_AGENTS


def test_get_agent_driver():
    assert isinstance(get_agent_driver("pi"), PiAgentDriver)
    assert isinstance(get_agent_driver("opencode"), OpenCodeDriver)
    assert isinstance(get_agent_driver("antigravity"), AntigravityDriver)
    assert isinstance(get_agent_driver("claude"), ClaudeDriver)

    for invalid_agent in ("default", "open-code", "agy", "claude-code", "unknown", ""):
        with pytest.raises(ValueError):
            get_agent_driver(invalid_agent)


def test_pi_driver_contracts(tmp_path):
    driver = PiAgentDriver()
    assert driver.name == "pi"
    assert driver.required_tools == ["pi"]
    assert driver.get_command(["--foo", "bar"]) == ["--foo", "bar"]
    assert driver.get_environment() == {}
    assert driver.get_t3_driver() == "pi"

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


def test_opencode_driver_contracts(tmp_path):
    driver = OpenCodeDriver()
    assert driver.name == "opencode"
    assert driver.required_tools == ["opencode"]
    assert driver.get_command(["run", "main.py"]) == ["run", "main.py"]
    assert driver.get_environment()["OPENAI_API_KEY"] == "OPENAI_API_KEY_PLACEHOLDER"
    assert driver.get_t3_driver() is None

    project_dir = tmp_path / "project"
    mounts = driver.get_mounts(project_dir)
    assert len(mounts) == 1
    assert mounts[0].destination == "/home/agent/.config/opencode"

    server_configs = [{"name": "qwen", "baseUrl": "http://llama:9999/v1"}]
    gateway_configs = [{"name": "opper", "baseUrl": "https://api.opper.ai"}]
    driver.synthesize_config(server_configs, gateway_configs, "qwen", project_dir)

    cfg_file = project_dir / ".pa-container" / "agents" / "opencode" / "config.json"
    assert cfg_file.is_file()
    cfg_data = json.loads(cfg_file.read_text())
    assert cfg_data["default_model"] == "qwen"
    assert "qwen" in cfg_data["providers"]
    assert cfg_data["providers"]["qwen"]["base_url"] == "http://llama:9999/v1"
    assert "opper" in cfg_data["providers"]
    assert cfg_data["providers"]["opper"]["api_key"] == "OPPER_API_KEY_PLACEHOLDER"


def test_antigravity_driver_contracts(tmp_path):
    driver = AntigravityDriver()
    assert driver.name == "antigravity"
    assert driver.required_tools == ["antigravity"]
    assert driver.get_command(["--goal", "audit"]) == ["--goal", "audit"]
    assert driver.get_environment()["GEMINI_API_KEY"] == "GEMINI_API_KEY_PLACEHOLDER"
    assert driver.get_t3_driver() is None

    project_dir = tmp_path / "project"
    mounts = driver.get_mounts(project_dir)
    assert len(mounts) == 1
    assert mounts[0].destination == "/home/agent/.gemini/antigravity"

    server_configs = [{"name": "local-model", "baseUrl": "http://llama:9999/v1"}]
    driver.synthesize_config(server_configs, [], "local-model", project_dir)

    cfg_file = project_dir / ".pa-container" / "agents" / "antigravity" / "config.json"
    assert cfg_file.is_file()
    cfg_data = json.loads(cfg_file.read_text())
    assert cfg_data["defaultModel"] == "local-model"
    assert len(cfg_data["models"]) == 1
    assert cfg_data["models"][0]["name"] == "local-model"


def test_claude_driver_contracts(tmp_path):
    driver = ClaudeDriver()
    assert driver.name == "claude"
    assert driver.required_tools == ["claude-code"]
    assert driver.get_command(["-p", "hello"]) == ["-p", "hello"]
    env = driver.get_environment()
    assert env["ANTHROPIC_API_KEY"] == "ANTHROPIC_API_KEY_PLACEHOLDER"
    assert env["CLAUDE_CONFIG_DIR"] == "/home/agent/.claude"
    assert driver.get_t3_driver() == "claudeAgent"

    project_dir = tmp_path / "project"
    mounts = driver.get_mounts(project_dir)
    assert len(mounts) == 1
    assert mounts[0].destination == "/home/agent/.claude"

    server_configs = [{"name": "local-claude", "baseUrl": "http://llama:9999/v1"}]
    driver.synthesize_config(server_configs, [], "claude-3-7-sonnet", project_dir)

    cfg_file = project_dir / ".pa-container" / "agents" / "claude" / "claude.json"
    assert cfg_file.is_file()
    cfg_data = json.loads(cfg_file.read_text())
    assert cfg_data["model"] == "claude-3-7-sonnet"
    assert cfg_data["baseUrl"] == "http://llama:9999/v1"

    settings_file = project_dir / ".pa-container" / "agents" / "claude" / "settings.json"
    assert settings_file.is_file()
    settings_data = json.loads(settings_file.read_text())
    assert settings_data["model"] == "claude-3-7-sonnet"
    assert settings_data["env"]["ANTHROPIC_BASE_URL"] == "http://llama:9999/v1"
