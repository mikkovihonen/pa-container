from __future__ import annotations

import json
from pathlib import Path

import pytest
from pa_packages.agents.host.registry import (
    AVAILABLE_AGENTS,
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

    # Single-agent mode: default when omitted
    assert resolve_selected_agent_names(None, enabled, "pi", multi_agent=False) == ("pi", ["pi"])
    assert resolve_selected_agent_names(None, enabled, "opencode", multi_agent=False) == ("opencode", ["opencode"])

    # Multi-agent mode: all enabled agents when omitted
    assert resolve_selected_agent_names(None, enabled, "pi", multi_agent=True) == (
        "pi",
        ["pi", "opencode", "claude"],
    )
    assert resolve_selected_agent_names(None, ["opencode"], "pi", multi_agent=True) == ("opencode", ["opencode"])

    # 'all' keyword
    assert resolve_selected_agent_names("all", enabled, "pi", multi_agent=False) == (
        "pi",
        ["pi", "opencode", "claude"],
    )
    assert resolve_selected_agent_names("ALL", enabled, "opencode", multi_agent=True) == (
        "opencode",
        ["pi", "opencode", "claude"],
    )

    # Single agent
    assert resolve_selected_agent_names("opencode", enabled, "pi", multi_agent=True) == ("opencode", ["opencode"])
    assert resolve_selected_agent_names("pi", enabled, "opencode", multi_agent=False) == ("pi", ["pi"])

    # Comma-separated list with trimming and deduplication
    assert resolve_selected_agent_names("opencode, pi", enabled, "claude", multi_agent=True) == (
        "opencode",
        ["opencode", "pi"],
    )
    assert resolve_selected_agent_names("pi, opencode, pi", enabled, "claude", multi_agent=False) == (
        "pi",
        ["pi", "opencode"],
    )

    # Errors: empty, unknown agent, disabled agent
    with pytest.raises(ValueError, match="Invalid empty"):
        resolve_selected_agent_names("", enabled, "pi", multi_agent=False)
    with pytest.raises(ValueError, match="Unknown agent"):
        resolve_selected_agent_names("unknown", enabled, "pi", multi_agent=False)
    with pytest.raises(ValueError, match="Unknown agent"):
        resolve_selected_agent_names("opencode,foobar", enabled, "pi", multi_agent=False)
    with pytest.raises(ValueError, match="is not enabled"):
        resolve_selected_agent_names("antigravity", enabled, "pi", multi_agent=False)


def test_get_agent_driver():
    assert get_agent_driver("pi").name == "pi"
    assert get_agent_driver("opencode").name == "opencode"
    assert get_agent_driver("antigravity").name == "antigravity"
    assert get_agent_driver("claude").name == "claude"

    for invalid_agent in ("default", "open-code", "agy", "claude-code", "unknown", ""):
        with pytest.raises(ValueError):
            get_agent_driver(invalid_agent)


def test_get_command():
    pi = get_agent_driver("pi")
    assert pi.get_command([]) == ["pi"]
    assert pi.get_command(["--foo", "bar"]) == ["pi", "--foo", "bar"]
    assert pi.get_command(["pi", "--foo"]) == ["pi", "--foo"]

    opencode = get_agent_driver("opencode")
    assert opencode.get_command([]) == ["opencode"]
    assert opencode.get_command(["run", "main.py"]) == ["opencode", "run", "main.py"]

    claude = get_agent_driver("claude")
    assert claude.get_command([]) == ["claude"]
    assert claude.get_command(["-p", "hello"]) == ["claude", "-p", "hello"]

    agy = get_agent_driver("antigravity")
    assert agy.get_command([]) == ["agy"]
    assert agy.get_command(["--goal", "audit"]) == ["agy", "--goal", "audit"]


def test_agent_native_gateways_filtered_per_agent(tmp_path: Path):
    opencode = get_agent_driver("opencode")
    pi = get_agent_driver("pi")
    claude = get_agent_driver("claude")
    antigravity = get_agent_driver("antigravity")

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
    opencode.synthesize_config([], all_gateways, "opper", project_dir)
    opencode_cfg = json.loads((project_dir / ".pa-container" / "agents" / "opencode" / "opencode.json").read_text())
    assert "anthropic-account" not in opencode_cfg["provider"]
    assert "google-account" not in opencode_cfg["provider"]
    assert "opper" in opencode_cfg["provider"]
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


def test_entrypoint_sh_no_single_quote_collisions():
    """Verify that coding-agent/entrypoint.sh has zero single quotes inside the gosu bash -c block."""
    import re
    import subprocess

    entrypoint_path = Path(__file__).resolve().parent.parent.parent.parent.parent / "coding-agent" / "entrypoint.sh"
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


def test_entrypoint_sh_no_hardcoded_agent_references():
    """Verify that coding-agent/entrypoint.sh has zero hardcoded coding agent names or paths."""
    entrypoint_path = Path(__file__).resolve().parent.parent.parent.parent.parent / "coding-agent" / "entrypoint.sh"
    content = entrypoint_path.read_text(encoding="utf-8")
    for agent in ("pi", "claude", "opencode", "antigravity"):
        assert f".{agent}" not in content, f"Found hardcoded .{agent} path in entrypoint.sh"
        assert f":-{agent}" not in content, f"Found hardcoded default agent fallback :-{agent} in entrypoint.sh"


def test_synthesize_config_projects_package_mcp_servers(tmp_path: Path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir(parents=True)
    cfg_dir = project_dir / ".pa-container"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text("packages:\n  - source-control:\n      - github\n  - podman: []\n")

    # Claude Code
    claude = get_agent_driver("claude")
    claude.synthesize_config([], [], "claude-3-7-sonnet", project_dir)
    claude_settings = json.loads((claude.get_state_dir(project_dir) / "settings.json").read_text())
    assert "mcpServers" in claude_settings
    assert "github" in claude_settings["mcpServers"]
    assert "docker" in claude_settings["mcpServers"]

    # OpenCode
    opencode = get_agent_driver("opencode")
    opencode.synthesize_config([], [], "test-model", project_dir)
    opencode_cfg = json.loads((opencode.get_state_dir(project_dir) / "opencode.json").read_text())
    assert "mcp" in opencode_cfg
    assert "github" in opencode_cfg["mcp"]

    # Antigravity
    antigravity = get_agent_driver("antigravity")
    antigravity.synthesize_config([], [], "gemini-2.5-pro", project_dir)
    mcp_file = antigravity.get_state_dir(project_dir) / "mcp_config.json"
    assert mcp_file.is_file()
    agy_mcp = json.loads(mcp_file.read_text())
    assert "mcpServers" in agy_mcp
    assert "docker" in agy_mcp["mcpServers"]
