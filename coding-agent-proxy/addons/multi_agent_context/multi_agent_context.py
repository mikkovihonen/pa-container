from __future__ import annotations

"""
mitmproxy addon: Multi-Agent Context

Maps incoming proxy connections to specific agent policies based on:
1. Ephemeral source port mapped by the local UDS bridge (Zero-Port mode)
2. Direct Unix Domain Socket path (sockname)
3. Direct listening port (legacy TCP mode)

Injects identity metadata into flow.metadata (pa_agent_id, pa_agent_user, pa_agent_driver, pa_policy)
so downstream addons (Allowlist, TokenReplacer, FlowExport) can enforce per-agent isolation.
"""

import asyncio
import contextlib
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml
from mitmproxy import ctx, http

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from mitmproxy.addonmanager import Loader

log = logging.getLogger(__name__)


@dataclass
class AgentPolicy:
    agent_id: str
    user: str = "agent"
    driver: str = "pi"
    allowed_hosts: list[str] = field(default_factory=list)
    token_placeholders: dict[str, str] = field(default_factory=dict)
    flow_log_path: str = ""
    socket_path: str = ""


class MultiAgentContextAddon:
    """Mitmproxy addon that maps listening Unix Domain Sockets or ports to AgentPolicy instances."""

    def __init__(
        self,
        port_map: dict[int, AgentPolicy] | None = None,
        socket_map: dict[str, AgentPolicy] | None = None,
    ) -> None:
        self.port_map: dict[int, AgentPolicy] = port_map or {}
        self.socket_map: dict[str, AgentPolicy] = socket_map or {}
        self.ephemeral_map: dict[int, AgentPolicy] = {}
        self.servers: list[asyncio.Server] = []
        self.config_path: str | None = os.environ.get("PA_MULTI_AGENT_CONFIG")
        if self.config_path:
            self._load_config(self.config_path)

    def load(self, loader: Loader) -> None:
        loader.add_option(
            "multi_agent_config",
            str,
            self.config_path or "",
            "Path to the multi-agent YAML/JSON configuration file.",
        )

    def configure(self, updated: set[str]) -> None:
        if "multi_agent_config" in updated:
            cfg_path = getattr(ctx.options, "multi_agent_config", "")
            if cfg_path:
                self._load_config(cfg_path)

    async def running(self) -> None:
        await self._start_uds_listeners()

    def done(self) -> None:
        for srv in self.servers:
            srv.close()
        self.servers.clear()

    async def _pipe(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await r.read(65536)
                if not data:
                    break
                w.write(data)
                await w.drain()
        except Exception:
            pass
        finally:
            with contextlib.suppress(Exception):
                w.close()

    async def _handle_uds_connection(
        self,
        client_r: asyncio.StreamReader,
        client_w: asyncio.StreamWriter,
        policy: AgentPolicy,
        mitm_port: int,
    ) -> None:
        try:
            proxy_r, proxy_w = await asyncio.open_connection("127.0.0.1", mitm_port)
            sock = proxy_w.get_extra_info("socket")
            if sock:
                src_port = sock.getsockname()[1]
                self.ephemeral_map[src_port] = policy
            asyncio.create_task(self._pipe(client_r, proxy_w))
            asyncio.create_task(self._pipe(proxy_r, client_w))
        except Exception as e:
            log.warning(f"[multi-agent] UDS bridge connection failed: {e}")
            with contextlib.suppress(Exception):
                client_w.close()

    async def _start_uds_listeners(self) -> None:
        mitm_port = 8080
        if hasattr(ctx, "options") and hasattr(ctx.options, "listen_port"):
            mitm_port = ctx.options.listen_port or 8080

        # Collect all unique absolute socket paths
        targets: dict[str, AgentPolicy] = {}
        for sock_path, policy in list(self.socket_map.items()):
            if sock_path.endswith(".sock") and os.path.isabs(sock_path):
                targets[sock_path] = policy

        # Ensure admin.sock is always included for health checks
        sockets_dir = "/home/mitmproxy/sockets"
        if targets:
            first_path = next(iter(targets.keys()))
            sockets_dir = os.path.dirname(first_path)
        admin_sock = os.path.join(sockets_dir, "admin.sock")
        if admin_sock not in targets:
            targets[admin_sock] = AgentPolicy(agent_id="admin", user="admin")

        def make_cb(
            pol: AgentPolicy, port: int
        ) -> Callable[[asyncio.StreamReader, asyncio.StreamWriter], Coroutine[Any, Any, None]]:
            async def cb(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
                await self._handle_uds_connection(r, w, pol, port)

            return cb

        for sock_path, policy in targets.items():
            try:
                os.makedirs(os.path.dirname(sock_path), exist_ok=True)
                if os.path.exists(sock_path):
                    with contextlib.suppress(Exception):
                        os.unlink(sock_path)
                srv = await asyncio.start_unix_server(
                    make_cb(policy, mitm_port),
                    sock_path,
                )
                self.servers.append(srv)
                log.info(f"[multi-agent] UDS bridge listening on {sock_path} -> 127.0.0.1:{mitm_port}")
            except Exception as e:
                log.warning(f"[multi-agent] Failed to bind UDS listener {sock_path}: {e}")

    def _load_config(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, "rb") as f:
                raw = yaml.safe_load(f) or {}
            agents = raw.get("agents", [])
            new_port_map: dict[int, AgentPolicy] = {}
            new_socket_map: dict[str, AgentPolicy] = {}

            for a in agents:
                agent_id = a.get("agent_id") or a.get("id", "unknown")
                port = a.get("proxy_port")
                t_port = a.get("transparent_port")
                sock_path = a.get("socket_path")
                if not sock_path and agent_id != "unknown":
                    sock_path = f"/home/mitmproxy/sockets/{agent_id}.sock"

                policy = AgentPolicy(
                    agent_id=agent_id,
                    user=a.get("user", "agent"),
                    driver=a.get("driver", "pi"),
                    allowed_hosts=list(a.get("allowlist") or a.get("allowed_hosts") or []),
                    token_placeholders=dict(a.get("token_placeholders") or {}),
                    flow_log_path=a.get("flow_log_path", ""),
                    socket_path=sock_path or "",
                )

                if sock_path:
                    new_socket_map[sock_path] = policy
                    base_name = os.path.basename(sock_path)
                    new_socket_map[base_name] = policy

                if port is not None and port > 0:
                    new_port_map[int(port)] = policy
                if t_port is not None and t_port > 0:
                    new_port_map[int(t_port)] = policy

            self.port_map = new_port_map
            self.socket_map = new_socket_map
            log.info(
                f"[multi-agent] Loaded {len(self.socket_map)} socket mappings and "
                f"{len(self.port_map)} port mappings from {path}"
            )
        except Exception as e:
            log.warning(f"[multi-agent] Failed to load config from {path}: {e}")

    def _resolve_policy(self, sockname: Any) -> AgentPolicy | None:
        if not sockname:
            return None

        # 1. Plain string or Path representation (Unix Domain Socket)
        if isinstance(sockname, str):
            policy = self.socket_map.get(sockname)
            if not policy:
                policy = self.socket_map.get(os.path.basename(sockname))
            return policy

        # 2. Tuple/List representation
        if isinstance(sockname, (list, tuple)):
            if len(sockname) == 1 and isinstance(sockname[0], str):
                s = sockname[0]
                return self.socket_map.get(s) or self.socket_map.get(os.path.basename(s))

            if len(sockname) >= 2:
                first = sockname[0]
                second = sockname[1]

                # Check if first element is a socket path string
                if isinstance(first, str) and (first.endswith(".sock") or "/" in first):
                    return self.socket_map.get(first) or self.socket_map.get(os.path.basename(first))

                # Check if second element is an integer port (legacy TCP)
                if isinstance(second, int):
                    return self.port_map.get(second)

        return None

    def requestheaders(self, flow: http.HTTPFlow) -> None:
        client_conn = getattr(flow, "client_conn", None)

        # 1. Check ephemeral port map from UDS bridge
        peername = getattr(client_conn, "peername", None)
        if peername and len(peername) >= 2 and isinstance(peername[1], int):
            policy = self.ephemeral_map.get(peername[1])
            if policy:
                flow.metadata["pa_agent_id"] = policy.agent_id
                flow.metadata["pa_agent_user"] = policy.user
                flow.metadata["pa_agent_driver"] = policy.driver
                flow.metadata["pa_policy"] = policy
                return

        # 2. Check direct sockname
        sockname = getattr(client_conn, "sockname", None)
        if not sockname:
            return

        policy = self._resolve_policy(sockname)
        if policy is None:
            if self.port_map or self.socket_map:
                flow.response = http.Response.make(403, b"PA-Proxy: Unregistered agent endpoint\n")
            return

        flow.metadata["pa_agent_id"] = policy.agent_id
        flow.metadata["pa_agent_user"] = policy.user
        flow.metadata["pa_agent_driver"] = policy.driver
        flow.metadata["pa_policy"] = policy


addons = [MultiAgentContextAddon()]
