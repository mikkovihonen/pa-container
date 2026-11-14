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

DEFAULT_BRIDGE_IP = "10.240.0.1"
DEFAULT_VM_NAME = "pa-factory-linux"


class IncusLinuxBackend(FactoryBackend):
    """Factory VM backend for Linux Desktop & Cloud environments using Incus / KVM."""

    def __init__(
        self,
        config: FactoryConfig | None = None,
        vm_name: str = DEFAULT_VM_NAME,
        bridge_ip: str = DEFAULT_BRIDGE_IP,
        ssh_user: str = "admin",
        ssh_port: int = 2222,
    ) -> None:
        self.config = config
        self.vm_name = vm_name
        self.bridge_ip = bridge_ip
        self.ssh_user = ssh_user
        self.ssh_port = ssh_port
        self.proxy_proc: subprocess.Popen[Any] | None = None

    def _execute_ssh_rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request to pa-agentd inside the VM over SSH stdio channel."""
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        cmd = [
            "ssh",
            "-p",
            str(self.ssh_port),
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            f"{self.ssh_user}@{self.bridge_ip}",
            "pa-agentd",
            "--stdio",
        ]
        try:
            res = subprocess.run(cmd, input=payload, capture_output=True, text=True, check=True, timeout=30)
            data = json.loads(res.stdout)
            return cast(dict[str, Any], data) if isinstance(data, dict) else {"error": "Invalid response"}
        except Exception as e:
            log.warning(f"SSH RPC {method} failed: {e}")
            return {"error": str(e)}

    def start_proxy(self, config: FactoryConfig) -> str:
        """Generate multi-agent proxy config and start coding-agent-proxy."""
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

        # Write proxy config to temp location
        proxy_config_path = Path.home() / ".cache" / "pa-container" / "multi_agent_proxy.yaml"
        proxy_config_path.parent.mkdir(parents=True, exist_ok=True)
        with proxy_config_path.open("w") as f:
            yaml.dump({"agents": proxy_rules}, f)

        log.info(f"Multi-agent proxy configured for {len(agents)} agents at {proxy_config_path}")
        return self.bridge_ip

    def ensure_factory_vm(self, config: FactoryConfig, proxy_ip: str) -> None:
        """Boot or ensure the Incus Factory VM is running with GPU passthrough."""
        log.info(f"Ensuring Incus Factory VM '{self.vm_name}' is running...")
        try:
            # Check if VM is running
            check = subprocess.run(["incus", "info", self.vm_name], capture_output=True, text=True)
            if check.returncode != 0:
                # Launch VM from image template
                launch_cmd = [
                    "incus",
                    "launch",
                    "images:fedora/41/cloud",
                    self.vm_name,
                    "--vm",
                    "-c",
                    f"limits.cpu={config.compute.cpus}",
                    "-c",
                    f"limits.memory={config.compute.memory_mb}MB",
                ]
                subprocess.run(launch_cmd, check=True, capture_output=True)

            # Apply GPU devices if requested
            if config.compute.gpu in ("optional", "required"):
                subprocess.run(
                    ["incus", "config", "device", "add", self.vm_name, "gpu", "gpu"],
                    capture_output=True,
                )
        except FileNotFoundError:
            log.warning("Incus binary not found on host. Running in simulation / mock mode.")

    def sync_git_to_vault(self, host_repo: Path, branch: str = "HEAD") -> str:
        """Push host Git state into the Factory VM's /var/pa-vault repository."""
        project_name = host_repo.name
        self._execute_ssh_rpc("init_vault", {"project_name": project_name})

        vault_git_url = f"ssh://{self.ssh_user}@{self.bridge_ip}:{self.ssh_port}/var/pa-vault/{project_name}.git"
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
            log.warning(f"Could not push to vault over SSH: {e}")

        return "HEAD"

    def launch_agent(self, agent: AgentSpec, task_prompt: str | None = None) -> int:
        """Instruct pa-agentd to provision user, update nftables, CoW clone, and start agent."""
        # 1. Provision user
        self._execute_ssh_rpc("provision_user", {"username": agent.id, "uid": agent.uid})

        # 2. Update firewall
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
            {"proxy_ip": self.bridge_ip, "dns_port": 5353, "agents": agents_data},
        )

        # 3. CoW clone workspace
        project_name = "default"
        self._execute_ssh_rpc(
            "cow_clone",
            {"project_name": project_name, "agent_id": agent.id, "branch_name": f"{agent.branch_prefix}/task"},
        )

        # 4. Launch agent process in sandbox
        cmd = ["pa-agent-entrypoint", "--driver", agent.driver]
        if task_prompt:
            cmd.extend(["--prompt", task_prompt])

        rpc_res = self._execute_ssh_rpc(
            "launch_agent",
            {
                "agent_id": agent.id,
                "command": cmd,
                "user": agent.id,
                "proxy_ip": self.bridge_ip,
                "proxy_port": agent.proxy_port or 8081,
            },
        )
        return 0 if "result" in rpc_res else 1

    def fetch_agent_branch(self, agent_id: str, host_repo: Path) -> str:
        """Fetch agent's branch from Factory VM Vault into host git worktree."""
        project_name = host_repo.name
        vault_git_url = f"ssh://{self.ssh_user}@{self.bridge_ip}:{self.ssh_port}/var/pa-vault/{project_name}.git"
        worktree_path = host_repo / ".pa" / "review" / agent_id

        # Fetch branches from vault
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
        """Stop all processes and shut down Incus VM."""
        with contextlib.suppress(Exception):
            subprocess.run(["incus", "stop", self.vm_name], capture_output=True)

    def get_status(self) -> dict[str, object]:
        rpc_res = self._execute_ssh_rpc("get_status", {})
        return {
            "backend": "linux-incus",
            "vm_name": self.vm_name,
            "bridge_ip": self.bridge_ip,
            "guest": rpc_res.get("result", {}),
        }
