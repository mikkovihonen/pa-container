from __future__ import annotations

from pathlib import Path

from guest_daemon.daemon import GuestDaemonService
from guest_daemon.firewall import generate_nftables_conf, generate_pf_conf
from guest_daemon.sandboxes.bubblewrap import build_bwrap_args
from guest_daemon.sandboxes.seatbelt import build_sandbox_exec_command, generate_seatbelt_profile


class TestGuestDaemonServiceRPC:
    def test_rpc_ping(self):
        svc = GuestDaemonService()
        res = svc.dispatch({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
        assert res["id"] == 1
        assert res["result"]["status"] == "ok"
        assert "platform" in res["result"]

    def test_rpc_method_not_found(self):
        svc = GuestDaemonService()
        res = svc.dispatch({"jsonrpc": "2.0", "id": 2, "method": "unknown_call", "params": {}})
        assert res["id"] == 2
        assert res["error"]["code"] == -32601

    def test_rpc_provision_user_mock(self, tmp_path):
        svc = GuestDaemonService()
        res = svc.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "provision_user",
                "params": {"username": "agent1", "uid": 2001, "home_base": str(tmp_path), "mock": True},
            }
        )
        assert res["result"]["user"] == "agent1"
        assert res["result"]["uid"] == 2001
        home = Path(res["result"]["home"])
        assert home.is_dir()
        assert (home / "workspace").is_dir()

    def test_rpc_update_firewall_mock(self, tmp_path):
        svc = GuestDaemonService()
        agents = [{"id": "agent1", "user": "agent1", "proxy_port": 8081, "transparent_port": 8091}]
        res = svc.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "update_firewall",
                "params": {"proxy_ip": "10.240.0.1", "dns_port": 5353, "agents": agents, "mock": True},
            }
        )
        assert res["result"]["status"] == "applied"

    def test_rpc_vault_and_cow_clone_mock(self, tmp_path):
        svc = GuestDaemonService(vault_root=tmp_path / "vault")
        init_res = svc.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "init_vault",
                "params": {"project_name": "test-repo"},
            }
        )
        assert init_res["result"]["project"] == "test-repo"
        repo_dir = Path(init_res["result"]["vault_repo"])
        assert (repo_dir / "hooks" / "pre-receive").is_file()

        workspace = tmp_path / "agent1" / "workspace"
        clone_res = svc.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "cow_clone",
                "params": {
                    "project_name": "test-repo",
                    "agent_id": "agent1",
                    "branch_name": "pa/agent1/feat",
                    "destination": str(workspace),
                    "mock_cow": True,
                },
            }
        )
        assert clone_res["result"]["status"] == "cloned"
        assert workspace.is_dir()

    def test_rpc_launch_agent_mock(self, tmp_path):
        svc = GuestDaemonService()
        home = tmp_path / "agent1"
        home.mkdir()
        (home / "workspace").mkdir()

        res = svc.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "launch_agent",
                "params": {
                    "agent_id": "agent1",
                    "command": ["echo", "hello"],
                    "user": "agent1",
                    "proxy_ip": "10.240.0.1",
                    "proxy_port": 8081,
                    "home_dir": str(home),
                    "mock": True,
                },
            }
        )
        assert res["result"]["status"] == "started"
        assert res["result"]["mock"] is True
        assert len(res["result"]["command"]) > 0


class TestFirewallGeneration:
    def test_generate_pf_conf(self):
        agents = [
            {"id": "agent1", "user": "agent1", "proxy_port": 8081, "transparent_port": 8091},
            {"id": "agent2", "user": "agent2", "proxy_port": 8082, "transparent_port": 8092},
        ]
        conf = generate_pf_conf("192.168.64.1", 5353, agents)
        assert 'proxy_ip = "192.168.64.1"' in conf
        assert "user { _pa_daemon, agent1, agent2 }" in conf
        assert "port { 8081, 8091 } user agent1" in conf
        assert "port { 8082, 8092 } user agent2" in conf

    def test_generate_nftables_conf(self):
        agents = [
            {"id": "agent1", "user": "agent1", "proxy_port": 8081, "transparent_port": 8091},
            {"id": "agent2", "user": "agent2", "proxy_port": 8082, "transparent_port": 8092},
        ]
        conf = generate_nftables_conf("10.240.0.1", 5353, agents)
        assert "define PROXY_IP = 10.240.0.1" in conf
        assert 'meta skuid "agent1" tcp dport { 80, 443 } dnat to $PROXY_IP:8091' in conf
        assert 'meta skuid "agent1" ip daddr $PROXY_IP tcp dport { 8081, 8091 } accept' in conf


class TestSandboxes:
    def test_build_bwrap_args(self, tmp_path):
        home = tmp_path / "home" / "agent1"
        home.mkdir(parents=True)
        args = build_bwrap_args(
            user="agent1",
            home_dir=home,
            proxy_ip="10.240.0.1",
            proxy_port=8081,
            command=["pa-agent-entrypoint", "--driver", "pi"],
            extra_env={"CUSTOM_FLAG": "1"},
        )
        assert args[0] == "bwrap"
        assert "--unshare-pid" in args
        assert "HTTP_PROXY" in args
        assert "http://10.240.0.1:8081" in args
        assert "CUSTOM_FLAG" in args
        assert "pa-agent-entrypoint" in args

    def test_generate_seatbelt_profile(self):
        prof = generate_seatbelt_profile(
            user="agent1",
            proxy_ip="192.168.64.1",
            proxy_port=8081,
            other_users=["admin", "agent2"],
        )
        assert '(allow network-outbound (remote tcp "192.168.64.1:8081"))' in prof
        assert '(subpath "/Users/admin")' in prof
        assert '(subpath "/Users/agent2")' in prof
        assert '(subpath "/Users/agent1")' in prof
        assert "AGXDeviceUserClient" in prof

    def test_build_sandbox_exec_command(self, tmp_path):
        sb_file = tmp_path / "profile.sb"
        sb_file.write_text("(version 1)")
        cmd = build_sandbox_exec_command(sb_file, ["python3", "main.py"])
        assert cmd == ["sandbox-exec", "-f", str(sb_file), "python3", "main.py"]
