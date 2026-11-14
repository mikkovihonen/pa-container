from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from config import REPO_ROOT
from packages.dependencies import resolve_package_dependencies
from packages.discovery import discover_packages


def test_agent_orchestrators_manifests_discovered():
    manifests = discover_packages(REPO_ROOT)
    expected_packages = [
        "agent-orchestrators",
        "agent-orchestrators/base",
        "agent-orchestrators/worktrunk",
        "agent-orchestrators/zellij",
        "agent-orchestrators/t3",
        "agent-orchestrators/agentintercom",
    ]
    for pkg in expected_packages:
        assert pkg in manifests, f"Expected package '{pkg}' was not discovered"


def test_agent_orchestrators_default_dependency_resolution():
    resolved = resolve_package_dependencies({"agent-orchestrators": []})
    keys = list(resolved.keys())
    assert "agent-orchestrators/base" in keys
    assert "agent-orchestrators/worktrunk" in keys
    assert "agent-orchestrators" in keys
    # base must come before aggregator
    assert keys.index("agent-orchestrators/base") < keys.index("agent-orchestrators")


def test_agentintercom_cli_file_bus(tmp_path: Path):
    intercom_cli = REPO_ROOT / "pa_packages" / "agent-orchestrators" / "agentintercom" / "bin" / "agentintercom"
    assert intercom_cli.is_file()

    bus_dir = tmp_path / "intercom"
    env = {
        "PATH": "/bin:/usr/bin:/usr/local/bin",
        "PA_INTERCOM_DIR": str(bus_dir),
        "AGENTINTERCOM_PEER": "peer-alpha",
    }

    # 1. Register peer
    res = subprocess.run(
        [sys.executable, str(intercom_cli), "register", "--name", "peer-alpha"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Registered peer 'peer-alpha'" in res.stdout

    # 2. List peers
    res = subprocess.run(
        [sys.executable, str(intercom_cli), "peers", "--json"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    peers = json.loads(res.stdout)
    assert any(p["name"] == "peer-alpha" for p in peers)

    # 3. Send message from another peer
    env_beta = dict(env)
    env_beta["AGENTINTERCOM_PEER"] = "peer-beta"
    res = subprocess.run(
        [
            sys.executable,
            str(intercom_cli),
            "send",
            "--to",
            "peer-alpha",
            "--message",
            "Task assignment: update schema",
            "--json",
        ],
        env=env_beta,
        capture_output=True,
        text=True,
        check=True,
    )
    msg_data = json.loads(res.stdout)
    msg_id = msg_data["id"]
    assert msg_id.startswith("msg_")
    assert msg_data["from"] == "peer-beta"

    # 4. Read inbox as peer-alpha
    res = subprocess.run(
        [sys.executable, str(intercom_cli), "inbox", "--unread", "--json"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    inbox = json.loads(res.stdout)
    assert len(inbox) == 1
    assert inbox[0]["id"] == msg_id

    # 5. Acknowledge message
    res = subprocess.run(
        [sys.executable, str(intercom_cli), "ack", msg_id, "--json"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    ack_data = json.loads(res.stdout)
    assert ack_data["status"] == "acked"

    # 6. Verify inbox has no unread messages
    res = subprocess.run(
        [sys.executable, str(intercom_cli), "inbox", "--unread", "--json"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    inbox_after = json.loads(res.stdout)
    assert len(inbox_after) == 0


def test_pa_intercom_hook_dispatcher(tmp_path: Path):
    hook_cli = REPO_ROOT / "pa_packages" / "agent-orchestrators" / "agentintercom" / "bin" / "pa-intercom-hook"
    intercom_cli = REPO_ROOT / "pa_packages" / "agent-orchestrators" / "agentintercom" / "bin" / "agentintercom"
    assert hook_cli.is_file()

    bus_dir = tmp_path / "intercom"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    # Symlink agentintercom to bin_dir so hook finds it in PATH
    (bin_dir / "agentintercom").symlink_to(intercom_cli)

    env = {
        "PATH": f"{bin_dir}:/bin:/usr/bin:/usr/local/bin",
        "PA_INTERCOM_DIR": str(bus_dir),
        "PA_INTERCOM_PEER": "claude-test",
    }

    # Register
    subprocess.run(
        [sys.executable, str(hook_cli), "register", "--harness", "claude"],
        env=env,
        capture_output=True,
        check=True,
    )

    # Empty inbox returns 0 and nothing on stdout
    res = subprocess.run(
        [sys.executable, str(hook_cli), "drain-text", "--harness", "claude"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == ""

    # Send a message to claude-test
    env_sender = dict(env)
    env_sender["PA_INTERCOM_PEER"] = "sender"
    subprocess.run(
        [
            sys.executable,
            str(intercom_cli),
            "send",
            "--to",
            "claude-test",
            "--message",
            "Please review PR 42",
        ],
        env=env_sender,
        capture_output=True,
        check=True,
    )

    # check-context emits JSON with additionalContext
    res_ctx = subprocess.run(
        [sys.executable, str(hook_cli), "check-context", "--harness", "claude"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    ctx_data = json.loads(res_ctx.stdout)
    assert "additionalContext" in ctx_data["hookSpecificOutput"]
    assert "Please review PR 42" in ctx_data["hookSpecificOutput"]["additionalContext"]

    # check-stop emits JSON with decision: block
    res_stop = subprocess.run(
        [sys.executable, str(hook_cli), "check-stop", "--harness", "claude"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    stop_data = json.loads(res_stop.stdout)
    assert stop_data["decision"] == "block"
    assert "Please review PR 42" in stop_data["reason"]


def test_pa_intercom_mcp_server(tmp_path: Path):
    mcp_cli = REPO_ROOT / "pa_packages" / "agent-orchestrators" / "agentintercom" / "bin" / "pa-intercom-mcp"
    intercom_cli = REPO_ROOT / "pa_packages" / "agent-orchestrators" / "agentintercom" / "bin" / "agentintercom"
    hook_cli = REPO_ROOT / "pa_packages" / "agent-orchestrators" / "agentintercom" / "bin" / "pa-intercom-hook"
    assert mcp_cli.is_file()

    bus_dir = tmp_path / "intercom"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "agentintercom").symlink_to(intercom_cli)
    (bin_dir / "pa-intercom-hook").symlink_to(hook_cli)

    env = {
        "PATH": f"{bin_dir}:/bin:/usr/bin:/usr/local/bin",
        "PA_INTERCOM_DIR": str(bus_dir),
        "PA_INTERCOM_PEER": "mcp-agent",
    }

    # Test tools/list
    init_request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
    list_request = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
    input_data = init_request + list_request

    proc = subprocess.run(
        [sys.executable, str(mcp_cli)],
        input=input_data,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0]["id"] == 1
    assert lines[1]["id"] == 2
    tools = lines[1]["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "intercom_peers" in tool_names
    assert "intercom_send" in tool_names
    assert "intercom_inbox" in tool_names
    assert "intercom_ack" in tool_names
