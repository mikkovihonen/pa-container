from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from otlp_exporter import (
    OtlpExporterAddon,
    TaskContext,
    scrub_secrets,
)


def test_scrub_secrets():
    raw = (
        "User query with sk-ant-api03-1234567890abcdef1234567890 and "
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz and pa-tok-agent1-abcdef1234567890"
    )
    scrubbed = scrub_secrets(raw)
    assert "sk-" not in scrubbed
    assert "Bearer" not in scrubbed
    assert "pa-tok" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_task_context_defaults():
    ctx = TaskContext(task_id="test-task-1")
    assert ctx.task_id == "test-task-1"
    assert len(ctx.trace_id) == 32
    assert len(ctx.span_id) == 16


def test_task_context_from_dict():
    data = {
        "task_id": "feat-42",
        "trace_id": "1234567890abcdef1234567890abcdef",
        "span_id": "abcdef1234567890",
        "parent_span_id": "0000000000000000",
        "objective_id": "OBJ-1",
        "kr_ids": ["KR-1", "KR-2"],
        "req_ids": ["REQ-1"],
        "design_refs": ["web:button"],
        "agent_role": "design_engineer",
        "model_profile": "claude-3-7-sonnet",
    }
    ctx = TaskContext.from_dict(data)
    assert ctx.task_id == "feat-42"
    assert ctx.objective_id == "OBJ-1"
    assert ctx.kr_ids == ["KR-1", "KR-2"]
    assert ctx.agent_role == "design_engineer"


def test_is_llm_request():
    addon = OtlpExporterAddon()

    flow_anthropic = MagicMock()
    flow_anthropic.request.pretty_host = "api.anthropic.com"
    flow_anthropic.request.path = "/v1/messages"
    assert addon.is_llm_request(flow_anthropic)

    flow_openai = MagicMock()
    flow_openai.request.pretty_host = "api.openai.com"
    flow_openai.request.path = "/v1/chat/completions"
    assert addon.is_llm_request(flow_openai)

    flow_gemini = MagicMock()
    flow_gemini.request.pretty_host = "generativelanguage.googleapis.com"
    flow_gemini.request.path = "/v1beta/models/gemini-pro:generateContent"
    assert addon.is_llm_request(flow_gemini)

    flow_other = MagicMock()
    flow_other.request.pretty_host = "github.com"
    flow_other.request.path = "/api/v3"
    assert not addon.is_llm_request(flow_other)


def test_extract_llm_metrics_anthropic():
    addon = OtlpExporterAddon()
    flow = MagicMock()
    flow.request.pretty_host = "api.anthropic.com"
    flow.request.path = "/v1/messages"
    flow.request.content = json.dumps({"model": "claude-3-7-sonnet"}).encode()
    flow.response.content = json.dumps(
        {
            "model": "claude-3-7-sonnet-20250219",
            "usage": {"input_tokens": 150, "output_tokens": 45},
        }
    ).encode()

    system, model, prompt_tok, comp_tok, total_tok = addon.extract_llm_metrics(flow)
    assert system == "anthropic"
    assert model == "claude-3-7-sonnet-20250219"
    assert prompt_tok == 150
    assert comp_tok == 45
    assert total_tok == 195


def test_build_genai_span():
    addon = OtlpExporterAddon()
    flow = MagicMock()
    flow.request.timestamp_start = 1000.0
    flow.response.timestamp_end = 1001.5
    flow.response.status_code = 200

    ctx = TaskContext(
        task_id="feat-10",
        trace_id="11112222333344445555666677778888",
        span_id="aaaabbbbccccdddd",
        agent_role="design_engineer",
        objective_id="OBJ-01",
        kr_ids=["KR-01"],
    )

    payload = addon.build_genai_span(
        flow=flow,
        task_ctx=ctx,
        system="anthropic",
        model="claude-3-7-sonnet",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
    )

    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 1
    span = spans[0]
    assert span["name"] == "gen_ai.chat"
    assert span["traceId"] == ctx.trace_id
    assert span["parentSpanId"] == ctx.span_id

    attrs = {a["key"]: a["value"] for a in span["attributes"]}
    assert attrs["gen_ai.system"]["stringValue"] == "anthropic"
    assert attrs["gen_ai.usage.prompt_tokens"]["intValue"] == 100
    assert attrs["openinference.span.kind"]["stringValue"] == "LLM"
    assert attrs["pa.task_id"]["stringValue"] == "feat-10"
    assert attrs["pa.agent_role"]["stringValue"] == "design_engineer"
    assert attrs["pa.objective_id"]["stringValue"] == "OBJ-01"


def test_export_local_jsonl(tmp_path: Path):
    jsonl_path = tmp_path / "events.jsonl"
    addon = OtlpExporterAddon(provider="none", local_jsonl_path=str(jsonl_path))

    payload = {"test": "span_data"}
    addon._send_payload(payload)

    assert jsonl_path.is_file()
    content = jsonl_path.read_text(encoding="utf-8")
    assert "span_data" in content
