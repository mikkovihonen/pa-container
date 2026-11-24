from __future__ import annotations

"""
mitmproxy addon: OTLP Runtime Exporter & GenAI Telemetry Meter

Intercepts LLM requests/responses traversing the proxy, meters token usage,
and emits correlated OpenTelemetry GenAI + OpenInference spans to any configured
OTLP backend (e.g. Arize Phoenix at http://127.0.0.1:6006/v1/traces, Langfuse, or generic OTLP collector).
"""

import contextlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from mitmproxy import ctx, http

if TYPE_CHECKING:
    from mitmproxy.addonmanager import Loader

log = logging.getLogger(__name__)

# Patterns for secret scrubbing
SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_\-]{20,}"),
    re.compile(r"pa-tok-[a-zA-Z0-9_\-]+"),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE),
    re.compile(r"key-[a-zA-Z0-9_\-]{20,}"),
]


def scrub_secrets(text: str) -> str:
    """Scrub sensitive API keys and tokens from prompt/completion strings."""
    if not text:
        return ""
    scrubbed = text
    for pattern in SECRET_PATTERNS:
        scrubbed = pattern.sub("[REDACTED]", scrubbed)
    return scrubbed


def generate_span_id() -> str:
    """Generate 16-character hexadecimal span ID."""
    return secrets.token_hex(8)


class TaskContext:
    def __init__(
        self,
        task_id: str = "",
        trace_id: str = "",
        span_id: str = "",
        parent_span_id: str = "",
        objective_id: str = "",
        kr_ids: list[str] | None = None,
        req_ids: list[str] | None = None,
        design_refs: list[str] | None = None,
        agent_role: str = "",
        model_profile: str = "",
    ) -> None:
        self.task_id = task_id
        self.trace_id = trace_id or secrets.token_hex(16)
        self.span_id = span_id or generate_span_id()
        self.parent_span_id = parent_span_id
        self.objective_id = objective_id
        self.kr_ids = kr_ids or []
        self.req_ids = req_ids or []
        self.design_refs = design_refs or []
        self.agent_role = agent_role
        self.model_profile = model_profile

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskContext:
        return cls(
            task_id=data.get("task_id", ""),
            trace_id=data.get("trace_id", ""),
            span_id=data.get("span_id", ""),
            parent_span_id=data.get("parent_span_id", ""),
            objective_id=data.get("objective_id", ""),
            kr_ids=data.get("kr_ids", []),
            req_ids=data.get("req_ids", []),
            design_refs=data.get("design_refs", []),
            agent_role=data.get("agent_role", ""),
            model_profile=data.get("model_profile", ""),
        )


class OtlpExporterAddon:
    """Mitmproxy addon that meters LLM token flows and exports OTLP GenAI spans."""

    def __init__(
        self,
        provider: str = "phoenix",
        endpoint: str = "http://127.0.0.1:6006/v1/traces",
        bindings_path: str = "",
        local_jsonl_path: str = "",
        scrub_enabled: bool = True,
        auth_header: str = "",
    ) -> None:
        self.provider = os.environ.get("PA_OTLP_PROVIDER", provider)
        self.endpoint = os.environ.get("PA_OTLP_ENDPOINT", endpoint)
        self.bindings_path = os.environ.get("PA_PROXY_BINDINGS", bindings_path)
        self.local_jsonl_path = os.environ.get("PA_OTLP_LOCAL_JSONL", local_jsonl_path or ".pa/telemetry/events.jsonl")
        self.scrub_enabled = os.environ.get("PA_OTLP_SCRUB_SECRETS", str(scrub_enabled)).lower() == "true"
        self.auth_header = os.environ.get("PA_OTLP_AUTH_HEADER", auth_header)
        self._bindings_cache: dict[str, TaskContext] = {}
        self._last_bindings_mtime: float = 0.0

    def load(self, loader: Loader) -> None:
        loader.add_option(
            "otlp_provider",
            str,
            self.provider,
            "OTLP backend provider ('phoenix', 'langfuse', 'otlp_generic', 'none').",
        )
        loader.add_option(
            "otlp_endpoint",
            str,
            self.endpoint,
            "OTLP HTTP traces endpoint (e.g. http://127.0.0.1:6006/v1/traces).",
        )
        loader.add_option(
            "otlp_bindings",
            str,
            self.bindings_path,
            "Path to proxy-bindings.json file.",
        )

    def configure(self, updated: set[str]) -> None:
        if "otlp_provider" in updated:
            self.provider = getattr(ctx.options, "otlp_provider", self.provider)
        if "otlp_endpoint" in updated:
            self.endpoint = getattr(ctx.options, "otlp_endpoint", self.endpoint)
        if "otlp_bindings" in updated:
            self.bindings_path = getattr(ctx.options, "otlp_bindings", self.bindings_path)

    def _reload_bindings_if_changed(self) -> None:
        if not self.bindings_path or not os.path.isfile(self.bindings_path):
            return
        try:
            mtime = os.path.getmtime(self.bindings_path)
            if mtime > self._last_bindings_mtime:
                with open(self.bindings_path, encoding="utf-8") as f:
                    data = json.load(f)
                ports = data.get("ports", {})
                new_cache: dict[str, TaskContext] = {}
                for port_str, ctx_dict in ports.items():
                    new_cache[str(port_str)] = TaskContext.from_dict(ctx_dict)
                self._bindings_cache = new_cache
                self._last_bindings_mtime = mtime
        except Exception as e:
            log.debug("Failed to reload proxy bindings: %s", e)

    def resolve_task_context(self, flow: http.HTTPFlow) -> TaskContext:
        """Resolve TaskContext for a flow using port mapping or metadata."""
        self._reload_bindings_if_changed()

        # Check port from client connection address
        client_port = None
        if flow.client_conn and flow.client_conn.address:
            client_port = str(flow.client_conn.address[1])

        # Check server / dst port if proxy is running in port-per-agent mode
        dst_port = None
        if flow.server_conn and flow.server_conn.address:
            dst_port = str(flow.server_conn.address[1])

        ctx_found = None
        if client_port and client_port in self._bindings_cache:
            ctx_found = self._bindings_cache[client_port]
        elif dst_port and dst_port in self._bindings_cache:
            ctx_found = self._bindings_cache[dst_port]
        elif len(self._bindings_cache) == 1:
            # Single active agent default
            ctx_found = next(iter(self._bindings_cache.values()))

        if ctx_found:
            return ctx_found

        # Fallback anonymous task context
        agent_id = flow.metadata.get("pa_agent_id", "default-agent")
        return TaskContext(task_id=f"auto-{agent_id}")

    def is_llm_request(self, flow: http.HTTPFlow) -> bool:
        """Determine if an HTTP flow represents an LLM API call."""
        host = flow.request.pretty_host.lower()
        path = flow.request.path.lower()

        if "anthropic.com" in host and "/v1/messages" in path:
            return True
        if "openai.com" in host and "/chat/completions" in path:
            return True
        if "generativelanguage.googleapis.com" in host and "generatecontent" in path:
            return True
        return bool("/v1/chat/completions" in path or "/completion" in path)

    def extract_llm_metrics(self, flow: http.HTTPFlow) -> tuple[str, str, int, int, int]:
        """Extract (system, model, prompt_tokens, completion_tokens, total_tokens)."""
        host = flow.request.pretty_host.lower()
        path = flow.request.path.lower()

        system = "unknown"
        model = ""
        prompt_tokens = 0
        completion_tokens = 0

        # Try to parse request JSON for model
        with contextlib.suppress(Exception):
            req_json = json.loads(flow.request.content or b"{}")
            model = req_json.get("model", "")

        # Try to parse response JSON for usage
        resp_json: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            resp_json = json.loads(flow.response.content or b"{}") if flow.response else {}

        if "anthropic.com" in host or "/v1/messages" in path:
            system = "anthropic"
            model = resp_json.get("model", model)
            usage = resp_json.get("usage", {})
            prompt_tokens = usage.get("input_tokens", 0)
            completion_tokens = usage.get("output_tokens", 0)
        elif "openai.com" in host or "/chat/completions" in path:
            system = "openai"
            model = resp_json.get("model", model)
            usage = resp_json.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
        elif "generativelanguage.googleapis.com" in host:
            system = "gemini"
            usage = resp_json.get("usageMetadata", {})
            prompt_tokens = usage.get("promptTokenCount", 0)
            completion_tokens = usage.get("candidatesTokenCount", 0)
        else:
            system = "generic_llm"
            usage = resp_json.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

        total_tokens = prompt_tokens + completion_tokens
        return system, model, prompt_tokens, completion_tokens, total_tokens

    def build_genai_span(
        self,
        flow: http.HTTPFlow,
        task_ctx: TaskContext,
        system: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> dict[str, Any]:
        """Construct dual OTel GenAI + OpenInference resourceSpans JSON."""
        span_id = generate_span_id()
        now_nano = int(time.time() * 1_000_000_000)
        duration_nano = (
            int((flow.response.timestamp_end - flow.request.timestamp_start) * 1_000_000_000)
            if flow.response and flow.response.timestamp_end and flow.request.timestamp_start
            else 500_000_000
        )
        start_nano = str(now_nano - duration_nano)
        end_nano = str(now_nano)

        attributes: list[dict[str, Any]] = [
            {"key": "gen_ai.system", "value": {"stringValue": system}},
            {"key": "gen_ai.request.model", "value": {"stringValue": model}},
            {"key": "gen_ai.response.model", "value": {"stringValue": model}},
            {"key": "gen_ai.usage.prompt_tokens", "value": {"intValue": prompt_tokens}},
            {"key": "gen_ai.usage.completion_tokens", "value": {"intValue": completion_tokens}},
            {"key": "gen_ai.usage.total_tokens", "value": {"intValue": total_tokens}},
            {"key": "openinference.span.kind", "value": {"stringValue": "LLM"}},
            {"key": "llm.model_name", "value": {"stringValue": model}},
            {"key": "llm.token_count.prompt", "value": {"intValue": prompt_tokens}},
            {"key": "llm.token_count.completion", "value": {"intValue": completion_tokens}},
            {"key": "llm.token_count.total", "value": {"intValue": total_tokens}},
            {"key": "pa.task_id", "value": {"stringValue": task_ctx.task_id}},
        ]

        if task_ctx.agent_role:
            attributes.append({"key": "pa.agent_role", "value": {"stringValue": task_ctx.agent_role}})
        if task_ctx.objective_id:
            attributes.append({"key": "pa.objective_id", "value": {"stringValue": task_ctx.objective_id}})
        if task_ctx.kr_ids:
            attributes.append({"key": "pa.kr_ids", "value": {"stringValue": ",".join(task_ctx.kr_ids)}})
        if task_ctx.req_ids:
            attributes.append({"key": "pa.req_ids", "value": {"stringValue": ",".join(task_ctx.req_ids)}})
        if task_ctx.design_refs:
            attributes.append(
                {
                    "key": "pa.design_refs",
                    "value": {"stringValue": ",".join(task_ctx.design_refs)},
                }
            )
        if task_ctx.model_profile:
            attributes.append({"key": "pa.model_profile", "value": {"stringValue": task_ctx.model_profile}})

        status_code = 1 if (flow.response and flow.response.status_code < 400) else 2

        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "coding-agent-proxy"}},
                            {"key": "pa.task_id", "value": {"stringValue": task_ctx.task_id}},
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {
                                "name": "pa.proxy.otlp_exporter",
                                "version": "2.0.0",
                            },
                            "spans": [
                                {
                                    "traceId": task_ctx.trace_id,
                                    "spanId": span_id,
                                    "parentSpanId": task_ctx.span_id,
                                    "name": "gen_ai.chat",
                                    "kind": 3,  # SPAN_KIND_CLIENT
                                    "startTimeUnixNano": start_nano,
                                    "endTimeUnixNano": end_nano,
                                    "attributes": attributes,
                                    "status": {"code": status_code},
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        return payload

    def export_span_async(self, payload: dict[str, Any]) -> None:
        """Asynchronously dispatch payload to OTLP backend or local JSONL."""
        thread = threading.Thread(target=self._send_payload, args=(payload,), daemon=True)
        thread.start()

    def _send_payload(self, payload: dict[str, Any]) -> None:
        if self.provider.lower() == "none":
            self._write_local_jsonl(payload)
            return

        json_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=json_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if self.auth_header:
            req.add_header("Authorization", self.auth_header)

        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status >= 300:
                    log.warning("OTLP endpoint returned status %d. Writing to local JSONL.", resp.status)
                    self._write_local_jsonl(payload)
        except Exception as e:
            log.debug("OTLP export failed (%s). Writing to local JSONL fallback.", e)
            self._write_local_jsonl(payload)

    def _write_local_jsonl(self, payload: dict[str, Any]) -> None:
        try:
            if self.local_jsonl_path:
                os.makedirs(os.path.dirname(self.local_jsonl_path), exist_ok=True)
                with open(self.local_jsonl_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(payload) + "\n")
        except Exception as e:
            log.warning("Failed to write OTLP fallback JSONL: %s", e)

    def response(self, flow: http.HTTPFlow) -> None:
        """Process response, detect LLM streams, build and export span."""
        if not self.is_llm_request(flow):
            return

        task_ctx = self.resolve_task_context(flow)
        system, model, prompt_tokens, completion_tokens, total_tokens = self.extract_llm_metrics(flow)

        payload = self.build_genai_span(
            flow,
            task_ctx,
            system,
            model,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )

        self.export_span_async(payload)


addons = [OtlpExporterAddon()]
