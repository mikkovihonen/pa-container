from __future__ import annotations

from unittest.mock import MagicMock

from cli import (
    FactoryOptions,
    LogsOptions,
    ProxyOptions,
    ReviewOptions,
    handle_factory_command,
    handle_logs_command,
    handle_proxy_command,
    handle_review_command,
)
from review import review_agent_workspace


def test_review_agent_workspace_mock(tmp_path):
    wt = review_agent_workspace(
        agent_id="agent1",
        host_repo=tmp_path,
        mock=True,
    )
    assert wt == tmp_path / ".pa" / "review" / "agent1"
    assert wt.is_dir()


def test_handle_review_command(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
    options = ReviewOptions(agent="agent1")
    code = handle_review_command(options)
    assert code == 0


def test_handle_factory_command_lifecycle(monkeypatch):
    mock_backend = MagicMock()
    mock_backend.start_proxy.return_value = "192.168.64.1"
    mock_backend.get_status.return_value = {"backend": "macos-tart", "vm_name": "pa-factory", "guest": "ok"}
    monkeypatch.setattr("backends.base.get_backend", lambda cfg: mock_backend)

    # factory up
    code_up = handle_factory_command(FactoryOptions(action="up"))
    assert code_up == 0
    mock_backend.start_proxy.assert_called_once()
    mock_backend.ensure_factory_vm.assert_called_once()

    # factory down
    code_down = handle_factory_command(FactoryOptions(action="down"))
    assert code_down == 0
    mock_backend.stop_factory.assert_called_once()

    # factory status
    code_st = handle_factory_command(FactoryOptions(action="status"))
    assert code_st == 0
    mock_backend.get_status.assert_called_once()


def test_handle_logs_command_agent_filter(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
    logs_dir = tmp_path / ".pa-container" / "logs"
    logs_dir.mkdir(parents=True)
    agent_log = logs_dir / "flows-agent-agent1.jsonl"
    agent_log.write_text('{"flow": 1}\n{"flow": 2}\n')

    options = LogsOptions(agent="agent1")
    code = handle_logs_command(options)
    assert code == 0


def test_handle_proxy_command_with_factory_toml(tmp_path, monkeypatch):
    monkeypatch.setattr("cli.PROJECT_DIR", tmp_path)
    factory_toml = tmp_path / "factory.toml"
    factory_toml.write_text("""schema_version = "2.0"
[factory]
name = "test-factory"
[[agents]]
id = "lead"
uid = 2001
proxy_port = 8081
transparent_port = 8091
allowlist = ["api.anthropic.com"]
""")

    options = ProxyOptions()
    code = handle_proxy_command(options)
    assert code == 0
