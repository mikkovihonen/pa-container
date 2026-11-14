from __future__ import annotations

"""
mitmproxy addon: Multi-Agent Context

Maps incoming proxy connections to specific agent policies based on the local
listening Unix Domain Socket path or legacy port (sockname). Injects identity
metadata into flow.metadata (pa_agent_id, pa_agent_user, pa_agent_driver, pa_policy)
so downstream addons (Allowlist, TokenReplacer, FlowExport) can enforce per-agent
isolation.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml
from mitmproxy import ctx, http

if TYPE_CHECKING:
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

    def _load_config(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, "rb") as f:
                raw = yaml.safe_load(f) or {}
            agents = raw.get("agents", [])
            new_port_map: dict[int, AgentPolicy] = {}
            new_socket_map: dict[str, AgentPolicy] = {}
            new_modes_to_add: list[str] = []

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
                    mode_entry = f"regular@{sock_path}"
                    new_modes_to_add.append(mode_entry)

                if port is not None:
                    new_port_map[int(port)] = policy
                if t_port is not None:
                    new_port_map[int(t_port)] = policy

            self.port_map = new_port_map
            self.socket_map = new_socket_map
            log.info(
                f"[multi-agent] Loaded {len(self.socket_map)} socket mappings and "
                f"{len(self.port_map)} port mappings from {path}"
            )

            # Dynamically ensure mitmproxy mode options include new sockets
            if hasattr(ctx, "options") and hasattr(ctx.options, "mode"):
                current_modes = list(ctx.options.mode)
                updated = False
                for m in new_modes_to_add:
                    if m not in current_modes:
                        current_modes.append(m)
                        updated = True
                if updated:
                    ctx.options.mode = current_modes
                    log.info(f"[multi-agent] Dynamically updated mitmproxy modes to: {current_modes}")
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
