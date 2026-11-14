from __future__ import annotations

"""
mitmproxy addon: Multi-Agent Context

Maps incoming proxy connections to specific agent policies based on the local
listening port (sockname[1]). Injects identity metadata into flow.metadata
(pa_agent_id, pa_agent_user, pa_agent_driver, pa_policy) so downstream addons
(Allowlist, TokenReplacer, FlowExport) can enforce per-agent isolation.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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


class MultiAgentContextAddon:
    """Mitmproxy addon that maps listening ports to AgentPolicy instances."""

    def __init__(self, port_map: dict[int, AgentPolicy] | None = None) -> None:
        self.port_map: dict[int, AgentPolicy] = port_map or {}
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
            new_map: dict[int, AgentPolicy] = {}
            for a in agents:
                port = a.get("proxy_port")
                t_port = a.get("transparent_port")
                policy = AgentPolicy(
                    agent_id=a.get("agent_id") or a.get("id", "unknown"),
                    user=a.get("user", "agent"),
                    driver=a.get("driver", "pi"),
                    allowed_hosts=list(a.get("allowlist") or a.get("allowed_hosts") or []),
                    token_placeholders=dict(a.get("token_placeholders") or {}),
                    flow_log_path=a.get("flow_log_path", ""),
                )
                if port is not None:
                    new_map[int(port)] = policy
                if t_port is not None:
                    new_map[int(t_port)] = policy
            self.port_map = new_map
            log.info(f"[multi-agent] Loaded {len(self.port_map)} port mappings from {path}")
        except Exception as e:
            log.warning(f"[multi-agent] Failed to load config from {path}: {e}")

    def _resolve_policy(self, local_port: int) -> AgentPolicy | None:
        return self.port_map.get(local_port)

    def requestheaders(self, flow: http.HTTPFlow) -> None:
        client_conn = getattr(flow, "client_conn", None)
        sockname = getattr(client_conn, "sockname", None)
        if not sockname or len(sockname) < 2:
            return

        local_port = sockname[1]
        policy = self._resolve_policy(local_port)
        if policy is None:
            if self.port_map:
                flow.response = http.Response.make(403, b"PA-Proxy: Unregistered agent port\n")
            return

        flow.metadata["pa_agent_id"] = policy.agent_id
        flow.metadata["pa_agent_user"] = policy.user
        flow.metadata["pa_agent_driver"] = policy.driver
        flow.metadata["pa_policy"] = policy


addons = [MultiAgentContextAddon()]
