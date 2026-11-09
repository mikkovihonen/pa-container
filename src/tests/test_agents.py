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
    resolve_selected_agent_names,
)


def test_available_agents():
    assert "pi" in AVAILABLE_AGENTS
    assert "opencode" in AVAILABLE_AGENTS
    assert "antigravity" in AVAILABLE_AGENTS
    assert "claude" in AVAILABLE_AGENTS


def test_resolve_selected_agent_names():
    enabled = ["pi", "opencode", "claude"]

    # Non-T3 mode: default when omitted
    assert resolve_selected_agent_names(None, enabled, "pi", is_t3_mode=False) == ("pi", ["pi"])
    assert resolve_selected_agent_names(None, enabled, "opencode", is_t3_mode=False) == ("opencode", ["opencode"])

    # T3 mode: all enabled agents when omitted
    assert resolve_selected_agent_names(None, enabled, "pi", is_t3_mode=True) == ("pi", ["pi", "opencode", "claude"])
    assert resolve_selected_agent_names(None, ["opencode"], "pi", is_t3_mode=True) == ("opencode", ["opencode"])

    # 'all' keyword
    assert resolve_selected_agent_names("all", enabled, "pi", is_t3_mode=False) == ("pi", ["pi", "opencode", "claude"])
    assert resolve_selected_agent_names("ALL", enabled, "opencode", is_t3_mode=True) == (
        "opencode",
        ["pi", "opencode", "claude"],
    )

    # Single agent
    assert resolve_selected_agent_names("opencode", enabled, "pi", is_t3_mode=True) == ("opencode", ["opencode"])
    assert resolve_selected_agent_names("pi", enabled, "opencode", is_t3_mode=False) == ("pi", ["pi"])

    # Comma-separated list with trimming and deduplication
    assert resolve_selected_agent_names("opencode, pi", enabled, "claude", is_t3_mode=True) == (
        "opencode",
        ["opencode", "pi"],
    )
    assert resolve_selected_agent_names("pi, opencode, pi", enabled, "claude", is_t3_mode=False) == (
        "pi",
        ["pi", "opencode"],
    )

    # Errors: empty, unknown agent, disabled agent
    with pytest.raises(ValueError, match="Invalid empty"):
        resolve_selected_agent_names("", enabled, "pi", is_t3_mode=False)
    with pytest.raises(ValueError, match="Unknown agent"):
        resolve_selected_agent_names("unknown", enabled, "pi", is_t3_mode=False)
    with pytest.raises(ValueError, match="Unknown agent"):
        resolve_selected_agent_names("opencode,foobar", enabled, "pi", is_t3_mode=False)
    with pytest.raises(ValueError, match="is not enabled"):
        resolve_selected_agent_names("antigravity", enabled, "pi", is_t3_mode=False)


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
    meta = driver.get_t3_metadata()
    assert meta is not None
    assert meta.driver_kind == "pi"
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


def test_opencode_driver_contracts(tmp_path):
    driver = OpenCodeDriver()
    assert driver.name == "opencode"
    assert driver.required_tools == ["opencode"]
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


def test_antigravity_driver_contracts(tmp_path):
    driver = AntigravityDriver()
    assert driver.name == "antigravity"
    assert driver.required_tools == ["antigravity"]
    assert driver.get_command(["--goal", "audit"]) == ["--goal", "audit"]
    assert driver.get_environment()["GEMINI_API_KEY"] == "GEMINI_API_KEY_PLACEHOLDER"
    meta = driver.get_t3_metadata()
    assert meta is not None
    assert meta.driver_kind == "antigravity"
    assert meta.instance_id == "antigravity"
    assert meta.settings == {"authMethod": "oauth-personal"}

    project_dir = tmp_path / "project"
    mounts = driver.get_mounts(project_dir)
    assert len(mounts) == 2
    assert mounts[0].destination == "/home/agent/.gemini/antigravity"
    assert mounts[1].destination == "/home/agent/.gemini/config"

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


def test_claude_driver_contracts(tmp_path):
    driver = ClaudeDriver()
    assert driver.name == "claude"
    assert driver.required_tools == ["claude-code"]
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
