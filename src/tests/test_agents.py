from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

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
    assert driver.required_packages == ["pi"]
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


def test_antigravity_driver_contracts(tmp_path):
    driver = AntigravityDriver()
    assert driver.name == "antigravity"
    assert driver.required_packages == ["antigravity"]
    assert driver.get_command(["--goal", "audit"]) == ["--goal", "audit"]
    assert driver.get_environment()["GEMINI_API_KEY"] == "GEMINI_API_KEY_PLACEHOLDER"
    meta = driver.get_t3_metadata()
    assert meta is not None
    assert meta.driver_kind == "antigravity"
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


def test_claude_driver_contracts(tmp_path):
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


def test_agent_native_gateways_filtered_per_agent(tmp_path):
    opencode = OpenCodeDriver()
    pi = PiAgentDriver()
    claude = ClaudeDriver()
    antigravity = AntigravityDriver()

    project_dir = tmp_path / "project"

    gw_claude_native = {
        "name": "anthropic-account",
        "baseUrl": "https://api.anthropic.com/v1",
        "gatewayDef": type(
            "GW",
            (),
            {
                "gateway_type": "anthropic",
                "id": "anthropic-account",
                "agent": "claude",
                "auth": type("A", (), {"type": "agent-native"})(),
            },
        )(),
    }
    gw_google_native = {
        "name": "google-account",
        "baseUrl": "https://generativelanguage.googleapis.com",
        "gatewayDef": type(
            "GW",
            (),
            {
                "gateway_type": "gemini",
                "id": "google-account",
                "agent": "antigravity",
                "auth": type("A", (), {"type": "agent-native"})(),
            },
        )(),
    }
    gw_api_key = {
        "name": "opper",
        "baseUrl": "https://api.opper.ai",
        "gatewayDef": type(
            "GW",
            (),
            {
                "gateway_type": "openai-compat",
                "id": "opper",
                "agent": None,
                "auth": type("A", (), {"type": "api-key"})(),
            },
        )(),
    }

    all_gateways = [gw_claude_native, gw_google_native, gw_api_key]

    # Test is_gateway_enabled_for_agent contracts
    assert opencode.is_gateway_enabled_for_agent(gw_claude_native) is False
    assert opencode.is_gateway_enabled_for_agent(gw_google_native) is False
    assert opencode.is_gateway_enabled_for_agent(gw_api_key) is True

    assert pi.is_gateway_enabled_for_agent(gw_claude_native) is False
    assert pi.is_gateway_enabled_for_agent(gw_google_native) is False
    assert pi.is_gateway_enabled_for_agent(gw_api_key) is True

    assert claude.is_gateway_enabled_for_agent(gw_claude_native) is True
    assert claude.is_gateway_enabled_for_agent(gw_google_native) is False
    assert claude.is_gateway_enabled_for_agent(gw_api_key) is True

    assert antigravity.is_gateway_enabled_for_agent(gw_claude_native) is False
    assert antigravity.is_gateway_enabled_for_agent(gw_google_native) is True
    assert antigravity.is_gateway_enabled_for_agent(gw_api_key) is True

    # 1. OpenCode must not have anthropic-account or google-account in opencode.json
    opencode.synthesize_config([], all_gateways, None, project_dir)
    opencode_cfg = json.loads((project_dir / ".pa-container" / "agents" / "opencode" / "opencode.json").read_text())
    assert "anthropic-account" not in opencode_cfg["providers"]
    assert "google-account" not in opencode_cfg["providers"]
    assert "opper" in opencode_cfg["providers"]
    assert opencode_cfg["enabled_providers"] == ["opper"]
    assert opencode_cfg["model"] == "opper/opper"

    # 2. Pi must not have anthropic-account or google-account in models.json
    pi.synthesize_config([], all_gateways, None, project_dir)
    pi_cfg = json.loads((project_dir / ".pa-container" / "agents" / "pi" / "models.json").read_text())
    assert "anthropic-account" not in pi_cfg["providers"]
    assert "google-account" not in pi_cfg["providers"]
    assert "opper" in pi_cfg["providers"]

    # 3. Claude must not pick google-account when synthesizing
    claude.synthesize_config([], [gw_google_native], None, project_dir)
    claude_cfg = json.loads((project_dir / ".pa-container" / "agents" / "claude" / "claude.json").read_text())
    assert "baseUrl" not in claude_cfg


def test_sync_antigravity_token(tmp_path):
    """Verify that sync_antigravity_token on host never extracts from host binaries."""
    import hashlib

    from agents.t3 import sync_antigravity_token

    project_dir = tmp_path / "project"
    t3_dir = tmp_path / "t3"

    # When no token file exists, does not raise
    sync_antigravity_token(t3_dir, project_dir)
    assert not (t3_dir / "userdata").exists()

    # Create dummy token file
    token_dir = project_dir / ".pa-container" / "agents" / "antigravity" / "cli"
    token_dir.mkdir(parents=True)
    token_file = token_dir / "antigravity-oauth-token"
    token_file.write_text(
        json.dumps(
            {
                "token": {
                    "access_token": "dummy_access",
                    "refresh_token": "dummy_refresh_12345",
                },
                "auth_method": "consumer",
            }
        )
    )

    # 1. On fresh startup without existing acp_token.json:
    # Host does NOT extract anything from the host and does NOT create acp_token.json
    sync_antigravity_token(t3_dir, project_dir)
    key = hashlib.sha256(b"antigravity").hexdigest()
    acp_token_file = t3_dir / "userdata" / "providers" / "antigravity" / key / "antigravity-acp" / "acp_token.json"
    assert not acp_token_file.exists()

    # Provider status cache IS initialized on the host
    cache_file = t3_dir / "caches" / "antigravity.json"
    assert cache_file.is_file()
    cache_data = json.loads(cache_file.read_text())
    assert cache_data["status"] == "ready"
    assert cache_data["auth"]["status"] == "authenticated"
    assert "message" not in cache_data
    assert cache_data.get("checkedAt") is not None
    assert isinstance(cache_data.get("slashCommands"), list)
    assert isinstance(cache_data.get("skills"), list)
    assert len(cache_data["models"]) >= 1
    assert cache_data["models"][0]["slug"] == "gemini-3.8-flash"
    assert cache_data["models"][0]["isCustom"] is False

    # 2. When acp_token.json was already generated by the container session:
    # Host syncs the new refresh_token without touching any host binaries
    acp_token_file.parent.mkdir(parents=True, exist_ok=True)
    mock_id = "test-client-id.apps.googleusercontent.com"
    mock_sec = "GOC" + "SPX-test-secret-123456789012"
    acp_token_file.write_text(
        json.dumps(
            {
                "client_id": mock_id,
                "client_secret": mock_sec,
                "refresh_token": "old_refresh",
            }
        )
    )

    sync_antigravity_token(t3_dir, project_dir)
    updated_data = json.loads(acp_token_file.read_text())
    assert updated_data["refresh_token"] == "dummy_refresh_12345"
    assert updated_data["client_id"] == mock_id
    assert updated_data["client_secret"] == mock_sec


def test_extract_antigravity_credentials(tmp_path):
    """Verify that extract_antigravity_credentials parses container runtime archives."""
    import importlib.util
    import zipfile
    from pathlib import Path

    script_path = Path(__file__).resolve().parent.parent.parent / "coding-agent" / "t3-sync-antigravity.py"
    spec = importlib.util.spec_from_file_location("t3_sync_antigravity", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    extract_fn = mod.extract_antigravity_credentials

    # 1. Nonexistent file returns None
    assert extract_fn(search_paths=[tmp_path / "absent.par"]) is None

    # 2. Extract consumer credentials from zipapp
    mock_sec = "GOC" + "SPX-consumer_secret_123456789"
    mock_id = "11111-consumer.apps.googleusercontent.com"
    par_consumer = tmp_path / "consumer.par"
    with zipfile.ZipFile(par_consumer, "w") as z:
        z.writestr(
            "google3/cloud/developer_experience/antigravity_extensions/acp_server/ccpa_connection/oauth_manager.py",
            f'_DEFAULT_CLIENT_ID = "{mock_id}"\n_DEFAULT_CLIENT_SECRET = "{mock_sec}"\n',
        )
    res = extract_fn(auth_method="consumer", search_paths=[par_consumer])
    assert res == (mock_id, mock_sec)

    # 3. Extract business credentials from zipapp
    mock_biz_sec = "GOC" + "SPX-business_secret_12345678"
    mock_biz_id = "22222-business.apps.googleusercontent.com"
    par_biz = tmp_path / "business.par"
    with zipfile.ZipFile(par_biz, "w") as z:
        z.writestr(
            "google3/cloud/developer_experience/antigravity_extensions/acp_server/baic_connection/business_auth.py",
            f'_BUSINESS_CLIENT_ID = "{mock_biz_id}"\n_BUSINESS_CLIENT_SECRET = "{mock_biz_sec}"\n',
        )
    res_biz = extract_fn(auth_method="business", search_paths=[par_biz])
    assert res_biz == (mock_biz_id, mock_biz_sec)

    # 4. Extract from plain text file
    txt_file = tmp_path / "plain_script.py"
    txt_file.write_text(f'_DEFAULT_CLIENT_ID = "{mock_id}"\n_DEFAULT_CLIENT_SECRET = "{mock_sec}"\n')
    assert extract_fn(auth_method="consumer", search_paths=[txt_file]) == (mock_id, mock_sec)


def test_entrypoint_sh_no_single_quote_collisions():
    """Verify that coding-agent/entrypoint.sh has zero single quotes inside the gosu bash -c block."""
    import re
    import subprocess
    from pathlib import Path

    entrypoint_path = Path(__file__).resolve().parent.parent.parent / "coding-agent" / "entrypoint.sh"
    content = entrypoint_path.read_text(encoding="utf-8")

    match = re.search(r"exec gosu agent bash -c \x27(.*?)\x27 -- \"\$@\"", content, re.DOTALL)
    assert match is not None, "Could not find exec gosu agent bash -c block in entrypoint.sh"
    inner_script = match.group(1)

    # Any unescaped single quote in inner_script terminates bash -c '...' prematurely
    assert "'" not in inner_script, "Found single quote inside exec gosu agent bash -c block in entrypoint.sh"

    # Validate that the inner script is valid bash syntax
    proc = subprocess.run(["bash", "-n", "-c", inner_script], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"Inner script failed bash syntax check: {proc.stderr}"
    assert proc.stderr == ""


def test_t3_sync_antigravity_script(tmp_path, monkeypatch):
    """Verify standalone t3-sync-antigravity.py synchronizes OAuth token and caches."""
    import hashlib
    import importlib.util
    import os
    import subprocess
    import zipfile
    from pathlib import Path

    script_path = Path(__file__).resolve().parent.parent.parent / "coding-agent" / "t3-sync-antigravity.py"
    assert script_path.is_file()

    spec = importlib.util.spec_from_file_location("t3_sync_antigravity", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mock_par = tmp_path / "agy_acp_server.par"
    mock_sec = "GOC" + "SPX-mock_secret_script_12345"
    mock_id = "9876543210-script.apps.googleusercontent.com"
    with zipfile.ZipFile(mock_par, "w") as z:
        z.writestr(
            "google3/cloud/developer_experience/antigravity_extensions/acp_server/ccpa_connection/oauth_manager.py",
            f'_DEFAULT_CLIENT_ID = "{mock_id}"\n_DEFAULT_CLIENT_SECRET = "{mock_sec}"\n',
        )
    monkeypatch.setenv("ANTIGRAVITY_ACP_SERVER_PAR", str(mock_par))

    token_file = tmp_path / "token.json"
    t3_dir = tmp_path / "t3"
    gemini_acp_dir = tmp_path / "gemini_acp"

    # When token file does not exist, returns False
    assert mod.sync_antigravity(token_file, t3_dir, gemini_acp_dir) is False

    # Create dummy token file
    token_file.write_text(
        json.dumps(
            {
                "token": {
                    "access_token": "acc_123",
                    "refresh_token": "ref_456",
                }
            }
        )
    )

    # Test via direct function call
    assert mod.sync_antigravity(token_file, t3_dir, gemini_acp_dir) is True

    key = hashlib.sha256(b"antigravity").hexdigest()
    t3_token = t3_dir / "userdata" / "providers" / "antigravity" / key / "antigravity-acp" / "acp_token.json"
    assert t3_token.is_file()
    assert json.loads(t3_token.read_text())["refresh_token"] == "ref_456"
    assert json.loads(t3_token.read_text())["client_id"] == mock_id
    assert json.loads(t3_token.read_text())["client_secret"] == mock_sec

    gemini_token = gemini_acp_dir / "acp_token.json"
    assert gemini_token.is_file()
    assert json.loads(gemini_token.read_text())["refresh_token"] == "ref_456"
    assert json.loads(gemini_token.read_text())["client_id"] == mock_id
    assert json.loads(gemini_token.read_text())["client_secret"] == mock_sec

    cache_file = t3_dir / "caches" / "antigravity.json"
    assert cache_file.is_file()
    cache_data = json.loads(cache_file.read_text())
    assert cache_data["status"] == "ready"
    assert "message" not in cache_data
    assert cache_data.get("checkedAt") is not None
    assert isinstance(cache_data.get("slashCommands"), list)
    assert isinstance(cache_data.get("skills"), list)
    assert cache_data["models"][0]["slug"] == "gemini-3.8-flash"
    assert cache_data["models"][0]["isCustom"] is False

    # Test via CLI invocation
    t3_dir_cli = tmp_path / "t3_cli"
    gemini_cli = tmp_path / "gemini_cli"
    env = os.environ.copy()
    env["ANTIGRAVITY_ACP_SERVER_PAR"] = str(mock_par)
    res = subprocess.run(
        ["python3", str(script_path), str(token_file), str(t3_dir_cli), str(gemini_cli)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert res.returncode == 0
    t3_cli_token = t3_dir_cli / "userdata" / "providers" / "antigravity" / key / "antigravity-acp" / "acp_token.json"
    assert t3_cli_token.is_file()
    assert json.loads(t3_cli_token.read_text())["refresh_token"] == "ref_456"
    assert json.loads(t3_cli_token.read_text())["client_id"] == mock_id
    assert json.loads(t3_cli_token.read_text())["client_secret"] == mock_sec


def test_synthesize_config_projects_package_mcp_servers(tmp_path: Path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir(parents=True)
    cfg_dir = project_dir / ".pa-container"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text("packages:\n  - gh\n  - podman\n")

    # Claude Code
    claude = ClaudeDriver()
    claude.synthesize_config([], [], "claude-3-7-sonnet", project_dir)
    claude_settings = json.loads((claude.get_state_dir(project_dir) / "settings.json").read_text())
    assert "mcpServers" in claude_settings
    assert "github" in claude_settings["mcpServers"]
    assert "docker" in claude_settings["mcpServers"]

    # OpenCode
    opencode = OpenCodeDriver()
    opencode.synthesize_config([], [], "test-model", project_dir)
    opencode_cfg = json.loads((opencode.get_state_dir(project_dir) / "opencode.json").read_text())
    assert "mcpServers" in opencode_cfg
    assert "github" in opencode_cfg["mcpServers"]

    # Antigravity
    antigravity = AntigravityDriver()
    antigravity.synthesize_config([], [], "gemini-2.5-pro", project_dir)
    mcp_file = antigravity.get_state_dir(project_dir) / "mcp_config.json"
    assert mcp_file.is_file()
    agy_mcp = json.loads(mcp_file.read_text())
    assert "mcpServers" in agy_mcp
    assert "docker" in agy_mcp["mcpServers"]
