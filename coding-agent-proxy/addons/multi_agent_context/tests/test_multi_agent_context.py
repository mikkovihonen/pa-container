from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from mitmproxy.http import HTTPFlow, Response
from mitmproxy.test.tflow import tflow

ADDONS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ADDONS_DIR / "multi_agent_context"))
sys.path.insert(0, str(ADDONS_DIR / "allowlist"))
sys.path.insert(0, str(ADDONS_DIR / "token_replacer"))

from allowlist import AllowlistAddon
from multi_agent_context import AgentPolicy, MultiAgentContextAddon
from token_replacer import TokenReplacerAddon

_fe_spec = importlib.util.spec_from_file_location("proxy_flow_exporter", ADDONS_DIR / "flow_export" / "flow_export.py")
_fe_mod = importlib.util.module_from_spec(_fe_spec)
_fe_spec.loader.exec_module(_fe_mod)
FlowExporter = _fe_mod.FlowExporter


def _make_flow_with_port(hostname: str, local_port: int) -> HTTPFlow:
    flow = tflow()
    flow.request.host = hostname
    flow.request.headers["host"] = hostname
    # mock client_conn sockname: (client_ip, local_port)
    flow.client_conn.sockname = ("127.0.0.1", local_port)
    flow.metadata = {}
    return flow


def _make_flow_with_socket(hostname: str, sockname: Any) -> HTTPFlow:
    flow = tflow()
    flow.request.host = hostname
    flow.request.headers["host"] = hostname
    flow.client_conn.sockname = sockname
    flow.metadata = {}
    return flow


class TestMultiAgentContext:
    def test_routes_known_agent_port(self):
        policy1 = AgentPolicy(
            agent_id="agent1",
            user="agent1",
            driver="pi",
            allowed_hosts=["api.anthropic.com"],
            token_placeholders={"AGENT1_TOKEN": "secret1"},
        )
        policy2 = AgentPolicy(
            agent_id="agent2",
            user="agent2",
            driver="claude",
            allowed_hosts=["api.openai.com"],
            token_placeholders={"AGENT2_TOKEN": "secret2"},
        )
        addon = MultiAgentContextAddon(port_map={8081: policy1, 8082: policy2})

        flow1 = _make_flow_with_port("api.anthropic.com", 8081)
        addon.requestheaders(flow1)

        assert flow1.response is None
        assert flow1.metadata["pa_agent_id"] == "agent1"
        assert flow1.metadata["pa_policy"] == policy1

        flow2 = _make_flow_with_port("api.openai.com", 8082)
        addon.requestheaders(flow2)

        assert flow2.response is None
        assert flow2.metadata["pa_agent_id"] == "agent2"
        assert flow2.metadata["pa_policy"] == policy2

    def test_routes_known_agent_socket_path(self):
        policy1 = AgentPolicy(
            agent_id="architect",
            user="architect",
            driver="pi",
            allowed_hosts=["api.anthropic.com"],
            socket_path="/run/pa-container/sockets/architect.sock",
        )
        policy2 = AgentPolicy(
            agent_id="tester",
            user="tester",
            driver="pytest",
            allowed_hosts=["api.openai.com"],
            socket_path="/run/pa-container/sockets/tester.sock",
        )
        addon = MultiAgentContextAddon(
            socket_map={
                "/run/pa-container/sockets/architect.sock": policy1,
                "architect.sock": policy1,
                "/run/pa-container/sockets/tester.sock": policy2,
                "tester.sock": policy2,
            }
        )

        # 1. Full string path
        flow1 = _make_flow_with_socket("api.anthropic.com", "/run/pa-container/sockets/architect.sock")
        addon.requestheaders(flow1)
        assert flow1.response is None
        assert flow1.metadata["pa_agent_id"] == "architect"
        assert flow1.metadata["pa_policy"] == policy1

        # 2. Tuple with socket path
        flow2 = _make_flow_with_socket("api.openai.com", ("/run/pa-container/sockets/tester.sock", None))
        addon.requestheaders(flow2)
        assert flow2.response is None
        assert flow2.metadata["pa_agent_id"] == "tester"
        assert flow2.metadata["pa_policy"] == policy2

        # 3. Base name fallback
        flow3 = _make_flow_with_socket("api.anthropic.com", "architect.sock")
        addon.requestheaders(flow3)
        assert flow3.response is None
        assert flow3.metadata["pa_agent_id"] == "architect"

    def test_blocks_unregistered_agent_endpoint(self):
        policy1 = AgentPolicy(agent_id="agent1")
        addon = MultiAgentContextAddon(
            port_map={8081: policy1},
            socket_map={"/run/pa/agent1.sock": policy1},
        )

        # Unregistered port
        flow1 = _make_flow_with_port("example.com", 9999)
        addon.requestheaders(flow1)
        assert flow1.response is not None
        assert flow1.response.status_code == 403
        assert b"Unregistered agent endpoint" in flow1.response.content

        # Unregistered socket
        flow2 = _make_flow_with_socket("example.com", "/run/pa/rogue.sock")
        addon.requestheaders(flow2)
        assert flow2.response is not None
        assert flow2.response.status_code == 403
        assert b"Unregistered agent endpoint" in flow2.response.content

    def test_loads_socket_paths_from_config(self, tmp_path):
        cfg_file = tmp_path / "multi_agent_proxy.json"
        cfg_data = {
            "agents": [
                {
                    "agent_id": "lead-architect",
                    "user": "lead-architect",
                    "socket_path": str(tmp_path / "architect.sock"),
                    "allowlist": ["api.anthropic.com"],
                },
                {
                    "agent_id": "test-runner",
                    "user": "test-runner",
                    "allowlist": ["pypi.org"],
                },
            ]
        }
        cfg_file.write_text(json.dumps(cfg_data))

        addon = MultiAgentContextAddon()
        addon._load_config(str(cfg_file))

        # Explicit socket_path loaded
        assert str(tmp_path / "architect.sock") in addon.socket_map
        assert addon.socket_map[str(tmp_path / "architect.sock")].agent_id == "lead-architect"

        # Derived default socket path loaded
        default_path = "/home/mitmproxy/sockets/test-runner.sock"
        assert default_path in addon.socket_map
        assert addon.socket_map[default_path].agent_id == "test-runner"
        assert "test-runner.sock" in addon.socket_map

    def test_allowlist_enforces_per_agent_policy(self):
        policy_frontend = AgentPolicy(
            agent_id="frontend",
            allowed_hosts=["registry.npmjs.org"],
        )
        policy_backend = AgentPolicy(
            agent_id="backend",
            allowed_hosts=["pypi.org"],
        )
        ctx_addon = MultiAgentContextAddon(
            socket_map={
                "/run/frontend.sock": policy_frontend,
                "/run/backend.sock": policy_backend,
            }
        )
        allowlist_addon = AllowlistAddon(config_path="")

        # Frontend agent visits npm -> allowed
        flow1 = _make_flow_with_socket("registry.npmjs.org", "/run/frontend.sock")
        ctx_addon.requestheaders(flow1)
        allowlist_addon.request(flow1)
        assert flow1.response is None

        # Frontend agent visits pypi -> denied
        flow2 = _make_flow_with_socket("pypi.org", "/run/frontend.sock")
        ctx_addon.requestheaders(flow2)
        allowlist_addon.request(flow2)
        assert flow2.response is not None
        assert flow2.response.status_code == 403

        # Backend agent visits pypi -> allowed
        flow3 = _make_flow_with_socket("pypi.org", "/run/backend.sock")
        ctx_addon.requestheaders(flow3)
        allowlist_addon.request(flow3)
        assert flow3.response is None

    def test_flow_export_records_agent_id(self, tmp_path, monkeypatch):
        policy = AgentPolicy(
            agent_id="agent1",
            flow_log_path=str(tmp_path / "flows-agent1.jsonl"),
        )
        ctx_addon = MultiAgentContextAddon(socket_map={"/run/agent1.sock": policy})

        monkeypatch.setenv("FLOW_EXPORT_DIR", str(tmp_path))
        monkeypatch.setenv("FLOW_EXPORT_ENABLED", "true")
        export_addon = FlowExporter()

        flow = _make_flow_with_socket("api.anthropic.com", "/run/agent1.sock")
        ctx_addon.requestheaders(flow)
        flow.response = Response.make(200, b"OK")

        export_addon.response(flow)

        agent_file = tmp_path / "flows-agent1.jsonl"
        assert agent_file.is_file()
        content = agent_file.read_text()
        data = json.loads(content.strip())
        assert data.get("pa_agent_id") == "agent1"

    def test_token_placeholder_replacement_authorized(self):
        policy = AgentPolicy(
            agent_id="agent1",
            allowed_hosts=["api.openai.com"],
            token_placeholders={"pa-tok-agent1-12345678": "sk-real-openai-secret"},
        )
        ctx_addon = MultiAgentContextAddon(socket_map={"/run/agent1.sock": policy})
        replacer_addon = TokenReplacerAddon(config_path="")

        flow = _make_flow_with_socket("api.openai.com", "/run/agent1.sock")
        flow.request.headers["authorization"] = "Bearer pa-tok-agent1-12345678"
        ctx_addon.requestheaders(flow)
        replacer_addon.request(flow)

        assert flow.response is None
        assert flow.request.headers["authorization"] == "Bearer sk-real-openai-secret"

    def test_token_placeholder_blocked_unauthorized_host(self):
        policy = AgentPolicy(
            agent_id="agent1",
            allowed_hosts=["api.openai.com"],
            token_placeholders={"pa-tok-agent1-12345678": "sk-real-openai-secret"},
        )
        ctx_addon = MultiAgentContextAddon(socket_map={"/run/agent1.sock": policy})
        replacer_addon = TokenReplacerAddon(config_path="")

        flow = _make_flow_with_socket("evil-attacker.com", "/run/agent1.sock")
        flow.request.headers["authorization"] = "Bearer pa-tok-agent1-12345678"
        ctx_addon.requestheaders(flow)
        replacer_addon.request(flow)

        assert flow.response is not None
        assert flow.response.status_code == 403
