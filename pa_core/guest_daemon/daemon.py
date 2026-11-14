from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from guest_daemon.firewall import apply_firewall, generate_nftables_conf, generate_pf_conf
from guest_daemon.git_vault import GitVaultManager
from guest_daemon.sandboxes.bubblewrap import build_bwrap_args
from guest_daemon.sandboxes.seatbelt import build_sandbox_exec_command, generate_seatbelt_profile
from guest_daemon.users import ensure_agent_user

log = logging.getLogger("pa-agentd")

DEFAULT_SOCKET_PATH = Path("/var/run/pa-agentd.sock")


class GuestDaemonService:
    """Core JSON-RPC service provider running inside the Factory VM."""

    def __init__(self, vault_root: Path | None = None) -> None:
        self.vault_manager = GitVaultManager(vault_root=vault_root)
        self.active_processes: dict[str, subprocess.Popen[Any]] = {}

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a single JSON-RPC request to the appropriate handler."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if not method:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32600, "message": "Invalid Request"}}

        handler = getattr(self, f"rpc_{method}", None)
        if handler is None:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

        try:
            result = handler(**params)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as e:
            log.exception(f"Error handling RPC {method}: {e}")
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}

    # ─── RPC Methods ─────────────────────────────────────────────────────────────

    def rpc_ping(self) -> dict[str, Any]:
        return {"status": "ok", "platform": sys.platform}

    def rpc_provision_user(
        self,
        username: str,
        uid: int,
        home_base: str | None = None,
        mock: bool = False,
    ) -> dict[str, Any]:
        base_path = Path(home_base) if home_base else None
        home = ensure_agent_user(username=username, uid=uid, home_base=base_path, mock=mock)
        return {"user": username, "uid": uid, "home": str(home)}

    def rpc_update_firewall(
        self,
        proxy_ip: str,
        dns_port: int,
        agents: list[dict[str, Any]],
        control_port: int = 2222,
        mock: bool = False,
    ) -> dict[str, Any]:
        if sys.platform == "darwin":
            rules = generate_pf_conf(proxy_ip=proxy_ip, dns_port=dns_port, agents=agents, control_port=control_port)
        else:
            rules = generate_nftables_conf(
                proxy_ip=proxy_ip, dns_port=dns_port, agents=agents, control_port=control_port
            )

        path = apply_firewall(rules, mock=mock)
        return {"status": "applied", "path": str(path), "rules_len": len(rules)}

    def rpc_init_vault(self, project_name: str) -> dict[str, Any]:
        repo_path = self.vault_manager.init_bare_vault(project_name)
        return {"project": project_name, "vault_repo": str(repo_path)}

    def rpc_cow_clone(
        self,
        project_name: str,
        agent_id: str,
        branch_name: str | None = None,
        destination: str | None = None,
        mock_cow: bool = False,
    ) -> dict[str, Any]:
        if destination is None:
            home_base = Path("/Users" if sys.platform == "darwin" else "/home")
            dest_path = home_base / agent_id / "workspace"
        else:
            dest_path = Path(destination)

        cloned_path = self.vault_manager.cow_clone_workspace(
            project_name=project_name,
            destination=dest_path,
            agent_id=agent_id,
            branch_name=branch_name,
            mock_cow=mock_cow,
        )
        return {"status": "cloned", "workspace": str(cloned_path), "branch": branch_name or f"pa/{agent_id}/task"}

    def rpc_launch_agent(
        self,
        agent_id: str,
        command: list[str],
        user: str,
        proxy_ip: str,
        proxy_port: int,
        home_dir: str | None = None,
        dns_port: int = 5353,
        extra_env: dict[str, str] | None = None,
        mock: bool = False,
    ) -> dict[str, Any]:
        home = Path(home_dir) if home_dir else Path("/Users" if sys.platform == "darwin" else "/home") / user

        if sys.platform == "darwin":
            if mock:
                profile_file = Path(f"/tmp/mock_{user}.sb")
                wrapped_cmd = build_sandbox_exec_command(profile_file, command)
                return {"status": "started", "mock": True, "command": wrapped_cmd}

            # Synthesize seatbelt profile
            profile_dir = Path("/etc/pa/profiles")
            profile_dir.mkdir(parents=True, exist_ok=True)
            profile_file = profile_dir / f"{user}.sb"
            profile_content = generate_seatbelt_profile(
                user=user,
                proxy_ip=proxy_ip,
                proxy_port=proxy_port,
                dns_port=dns_port,
            )
            profile_file.write_text(profile_content)
            wrapped_cmd = build_sandbox_exec_command(profile_file, command)
        else:
            wrapped_cmd = build_bwrap_args(
                user=user,
                home_dir=home,
                proxy_ip=proxy_ip,
                proxy_port=proxy_port,
                command=command,
                extra_env=extra_env,
            )

        if mock:
            return {"status": "started", "mock": True, "command": wrapped_cmd}

        proc = subprocess.Popen(
            wrapped_cmd,
            cwd=str(home / "workspace" if (home / "workspace").exists() else home),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.active_processes[agent_id] = proc
        return {"status": "started", "pid": proc.pid, "command": wrapped_cmd}

    def rpc_get_status(self) -> dict[str, Any]:
        procs: dict[str, Any] = {}
        for k, p in list(self.active_processes.items()):
            poll = p.poll()
            procs[k] = {"pid": p.pid, "running": poll is None, "returncode": poll}
        return {"platform": sys.platform, "agents": procs}


def run_stdio_server(service: GuestDaemonService) -> None:
    """Read JSON-RPC requests from standard input, process and write to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            res = service.dispatch(req)
            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()
        except Exception as e:
            err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {e}"}}
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()


def run_unix_socket_server(service: GuestDaemonService, socket_path: Path) -> None:
    """Listen for JSON-RPC connections on a Unix domain socket."""
    if socket_path.exists():
        socket_path.unlink()
    socket_path.parent.mkdir(parents=True, exist_ok=True)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(16)
    os.chmod(socket_path, 0o660)

    log.info(f"pa-agentd listening on {socket_path}")
    try:
        while True:
            conn, _ = server.accept()
            with conn:
                f = conn.makefile("rwb")
                for line in f:
                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        continue
                    try:
                        req = json.loads(line_str)
                        res = service.dispatch(req)
                        out_bytes = (json.dumps(res) + "\n").encode("utf-8")
                        f.write(out_bytes)
                        f.flush()
                    except Exception as e:
                        err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {e}"}}
                        f.write((json.dumps(err) + "\n").encode("utf-8"))
                        f.flush()
    finally:
        server.close()
        if socket_path.exists():
            socket_path.unlink()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pa-agentd", description="PA-Container 2.0 Guest Agent Daemon")
    parser.add_argument("--stdio", action="store_true", help="Run in stdio mode (for SSH control channels)")
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET_PATH, help="Path to Unix domain socket")
    parser.add_argument("--exec", dest="exec_json", type=str, help="Execute a single JSON-RPC call and exit")

    args = parser.parse_args(argv)
    service = GuestDaemonService()

    if args.exec_json:
        req = json.loads(args.exec_json)
        res = service.dispatch(req)
        print(json.dumps(res))
    elif args.stdio:
        run_stdio_server(service)
    else:
        run_unix_socket_server(service, args.socket)


if __name__ == "__main__":
    main()
