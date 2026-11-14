from __future__ import annotations

import sys
from unittest.mock import MagicMock

from backends.base import get_backend
from backends.incus_linux import IncusLinuxBackend
from backends.tart_macos import TartMacOSBackend
from factory_schema import AgentSpec, ComputeSpec, FactoryConfig


def test_get_backend_auto_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    cfg = FactoryConfig(compute=ComputeSpec(backend="auto"))
    backend = get_backend(cfg)
    assert isinstance(backend, TartMacOSBackend)


def test_get_backend_auto_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    cfg = FactoryConfig(compute=ComputeSpec(backend="auto"))
    backend = get_backend(cfg)
    assert isinstance(backend, IncusLinuxBackend)


def test_get_backend_explicit():
    cfg_tart = FactoryConfig(compute=ComputeSpec(backend="macos-tart"))
    assert isinstance(get_backend(cfg_tart), TartMacOSBackend)

    cfg_incus = FactoryConfig(compute=ComputeSpec(backend="linux-incus"))
    assert isinstance(get_backend(cfg_incus), IncusLinuxBackend)


class TestTartMacOSBackend:
    def test_start_proxy_writes_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        cfg = FactoryConfig(agents=[AgentSpec(id="agent1", uid=2001, proxy_port=8081, allowlist=["api.anthropic.com"])])
        backend = TartMacOSBackend(config=cfg, proxy_host_ip="192.168.64.1")
        ip = backend.start_proxy(cfg)
        assert ip == "192.168.64.1"

        proxy_cfg_file = tmp_path / ".cache" / "pa-container" / "multi_agent_proxy.yaml"
        assert proxy_cfg_file.is_file()

    def test_launch_agent_rpc(self, monkeypatch):
        cfg = FactoryConfig()
        backend = TartMacOSBackend(config=cfg)

        mock_rpc = MagicMock(return_value={"result": {"status": "started"}})
        monkeypatch.setattr(backend, "_execute_ssh_rpc", mock_rpc)

        agent = AgentSpec(id="agent1", driver="pi", uid=2001, proxy_port=8081)
        code = backend.launch_agent(agent)
        assert code == 0
        assert mock_rpc.call_count == 4  # provision_user, update_firewall, cow_clone, launch_agent


class TestIncusLinuxBackend:
    def test_start_proxy_writes_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        cfg = FactoryConfig(agents=[AgentSpec(id="agent2", uid=2002, proxy_port=8082, allowlist=["pypi.org"])])
        backend = IncusLinuxBackend(config=cfg, bridge_ip="10.240.0.1")
        ip = backend.start_proxy(cfg)
        assert ip == "10.240.0.1"

    def test_launch_agent_rpc(self, monkeypatch):
        cfg = FactoryConfig()
        backend = IncusLinuxBackend(config=cfg)

        mock_rpc = MagicMock(return_value={"result": {"status": "started"}})
        monkeypatch.setattr(backend, "_execute_ssh_rpc", mock_rpc)

        agent = AgentSpec(id="agent2", driver="opencode", uid=2002, proxy_port=8082)
        code = backend.launch_agent(agent)
        assert code == 0
        assert mock_rpc.call_count == 4
