from __future__ import annotations

import contextlib
import json
import logging
import subprocess
from pathlib import Path
from typing import Any, cast

import yaml

from backends.base import FactoryBackend
from factory_schema import AgentSpec, FactoryConfig, resolve_agent_ports

log = logging.getLogger(__name__)

DEFAULT_TART_VM = "pa-factory-macos"
DEFAULT_TART_GATEWAY = "192.168.64.1"


class TartMacOSBackend(FactoryBackend):
    """Factory VM backend for Apple Silicon macOS Desktop environments using Tart + Softnet."""

    def __init__(
        self,
        config: FactoryConfig | None = None,
        vm_name: str = DEFAULT_TART_VM,
        proxy_host_ip: str = DEFAULT_TART_GATEWAY,
        ssh_user: str = "admin",
        ssh_port: int = 2222,
    ) -> None:
        self.config = config
        self.vm_name = vm_name
        self.proxy_host_ip = proxy_host_ip
        self.ssh_user = ssh_user
        self.ssh_port = ssh_port
        self.vm_proc: subprocess.Popen[Any] | None = None

    def _execute_ssh_rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request to pa-agentd inside the Tart VM over SSH stdio channel."""
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        cmd = [
            "ssh",
            "-p",
            str(self.ssh_port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"{self.ssh_user}@{self.proxy_host_ip}",
            "pa-agentd",
            "--stdio",
        ]
        try:
            res = subprocess.run(cmd, input=payload, capture_output=True, text=True, check=True, timeout=30)
            data = json.loads(res.stdout)
            return cast("dict[str, Any]", data) if isinstance(data, dict) else {"error": "Invalid response"}
        except Exception as e:
            log.warning(f"Tart SSH RPC {method} failed: {e}")
            return {"error": str(e)}

    def start_proxy(self, config: FactoryConfig) -> str:
        """Start coding-agent-proxy configured with multi-agent port mapping."""
        agents = resolve_agent_ports(config.agents)
        proxy_rules: list[dict[str, Any]] = []

        for a in agents:
            proxy_rules.append(
                {
                    "id": a.id,
                    "agent_id": a.id,
                    "user": a.id,
                    "driver": a.driver,
                    "proxy_port": a.proxy_port,
                    "transparent_port": a.transparent_port,
                    "allowed_hosts": a.allowlist,
                    "flow_log_path": f"/exports/flows-agent-{a.id}.jsonl",
                }
            )

        proxy_config_path = Path.home() / ".cache" / "pa-container" / "multi_agent_proxy.yaml"
        proxy_config_path.parent.mkdir(parents=True, exist_ok=True)
        with proxy_config_path.open("w") as f:
            yaml.dump({"agents": proxy_rules}, f)

        log.info(f"Tart proxy configured with host gateway {self.proxy_host_ip}")
        return self.proxy_host_ip

    def ensure_factory_vm(self, config: FactoryConfig, proxy_ip: str) -> None:
        """Launch the Tart macOS guest VM with Softnet locked to proxy IP."""
        log.info(f"Ensuring Tart macOS VM '{self.vm_name}' is running with Softnet locked to {proxy_ip}/32...")
        tart_cmd = [
            "tart",
            "run",
            "--net-softnet",
            f"--net-softnet-allow={proxy_ip}/32",
            "--no-clipboard",
            "--no-audio",
            self.vm_name,
        ]
        try:
            # Check if VM is already responsive over SSH
            check = subprocess.run(
                ["ssh", "-p", str(self.ssh_port), "-o", "ConnectTimeout=2", f"{self.ssh_user}@{proxy_ip}", "true"],
                capture_output=True,
            )
            if check.returncode != 0:
                self.vm_proc = subprocess.Popen(tart_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            log.warning("Tart CLI not installed on host. Running in simulation / mock mode.")

    def sync_git_to_vault(self, host_repo: Path, branch: str = "HEAD") -> str:
        """Push host Git repository into the macOS Factory VM /var/pa-vault."""
        project_name = host_repo.name
        self._execute_ssh_rpc("init_vault", {"project_name": project_name})

        vault_git_url = f"ssh://{self.ssh_user}@{self.proxy_host_ip}:{self.ssh_port}/var/pa-vault/{project_name}.git"
        try:
            res = subprocess.run(
                ["git", "push", vault_git_url, f"{branch}:refs/heads/main"],
                cwd=host_repo,
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=host_repo, capture_output=True, text=True)
                return rev.stdout.strip()
        except Exception as e:
            log.warning(f"Could not push to Tart vault: {e}")

        return "HEAD"

    def launch_agent(self, agent: AgentSpec, task_prompt: str | None = None) -> int:
        """Provision macOS POSIX user, apply pf firewall, APFS CoW clone, and start Seatbelt sandbox."""
        # 1. Provision user
        self._execute_ssh_rpc("provision_user", {"username": agent.id, "uid": agent.uid})

        # 2. Apply macOS pf firewall rules
        agents_data = [
            {
                "id": agent.id,
                "user": agent.id,
                "proxy_port": agent.proxy_port or 8081,
                "transparent_port": agent.transparent_port or 8091,
            }
        ]
        self._execute_ssh_rpc(
            "update_firewall",
            {"proxy_ip": self.proxy_host_ip, "dns_port": 5353, "agents": agents_data},
        )

        # 3. APFS CoW clone
        project_name = "default"
        self._execute_ssh_rpc(
            "cow_clone",
            {"project_name": project_name, "agent_id": agent.id, "branch_name": f"{agent.branch_prefix}/task"},
        )

        # 4. Start agent wrapped in Seatbelt
        cmd = ["pa-agent-entrypoint", "--driver", agent.driver]
        if task_prompt:
            cmd.extend(["--prompt", task_prompt])

        rpc_res = self._execute_ssh_rpc(
            "launch_agent",
            {
                "agent_id": agent.id,
                "command": cmd,
                "user": agent.id,
                "proxy_ip": self.proxy_host_ip,
                "proxy_port": agent.proxy_port or 8081,
            },
        )
        return 0 if "result" in rpc_res else 1

    def fetch_agent_branch(self, agent_id: str, host_repo: Path) -> str:
        """Fetch agent's branch from Factory VM Vault into host git worktree."""
        project_name = host_repo.name
        vault_git_url = f"ssh://{self.ssh_user}@{self.proxy_host_ip}:{self.ssh_port}/var/pa-vault/{project_name}.git"
        worktree_path = host_repo / ".pa" / "review" / agent_id

        subprocess.run(
            ["git", "fetch", vault_git_url, f"+refs/heads/pa/{agent_id}/*:refs/remotes/pa/{agent_id}/*"],
            cwd=host_repo,
            capture_output=True,
        )

        if not worktree_path.exists():
            worktree_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "worktree", "add", str(worktree_path), f"pa/{agent_id}/task"],
                cwd=host_repo,
                capture_output=True,
            )

        return str(worktree_path)

    def stop_factory(self) -> None:
        """Stop Tart VM instance."""
        with contextlib.suppress(Exception):
            subprocess.run(["tart", "stop", self.vm_name], capture_output=True)

    def get_status(self) -> dict[str, object]:
        rpc_res = self._execute_ssh_rpc("get_status", {})
        return {
            "backend": "macos-tart",
            "vm_name": self.vm_name,
            "proxy_host_ip": self.proxy_host_ip,
            "guest": rpc_res.get("result", {}),
        }
