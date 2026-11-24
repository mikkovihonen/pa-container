# Proxy Addon: OTLP Exporter

The `otlp_exporter` addon in `coding-agent-proxy` intercepts outbound LLM requests and completions, converts them into **OpenTelemetry (OTel)** and **OpenInference** GenAI spans, scrubs credentials, and asynchronously exports them to your configured OTLP collector.

---

## 1. Addon Pipeline Architecture

```mermaid
flowchart LR
    Agent["Agent in Factory VM"] -->|Outbound LLM Request| Proxy["coding-agent-proxy"]
    
    subgraph Addons["mitmproxy Addon Chain"]
        MAC["MultiAgentContextAddon"] --> AL["AllowlistAddon"]
        AL --> TR["TokenReplacerAddon"]
        TR --> FE["FlowExportAddon"]
        FE --> OTLP["otlp_exporter Addon"]
    end
    
    Proxy --> MAC
    OTLP -->|Exported Spans (/v1/traces)| Collector["OTLP Collector (Phoenix / Langfuse)"]
    Proxy -->|Real Secret Injected| Upstream["LLM API (Anthropic / OpenAI / Gemini)"]
```

---

## 2. Dynamic Task Context Correlation

To associate intercepted HTTP flows with the correct agent, feature, and business objective:

1. The host orchestrator (`pa-core`) writes current execution metadata to `.pa/proxy-bindings.json` at task start.
2. The `otlp_exporter` addon watches `.pa/proxy-bindings.json`.
3. When a request matches an LLM provider endpoint (e.g. `api.anthropic.com`, `api.openai.com`), the addon extracts:
    - `pa.task_id`: Current task ID.
    - `pa.trace_id`: Root trace identifier (making proxy spans children of `pa.task.run`).
    - `pa.objective_id` & `pa.kr_ids`: Strategic OKR correlation keys.
    - `pa.agent_id`: Inferred from the dedicated proxy port.

---

## 3. Zero-Knowledge Secret Scrubbing

Telemetry payloads must never leak credentials into observability backends. The `otlp_exporter` enforces in-memory payload scrubbing:

- **Authorization Headers:** Replaced with `[REDACTED]`.
- **API Keys in Body/Headers:** Patterns matching OpenAI (`sk-...`), Gemini (`AIza...`), GitHub (`ghp_...`), and Anthropic keys are masked.
- **HMAC Placeholders:** `pa-tok-<agent>-<nonce>` tokens are stripped before export.

---

## 4. OpenInference & GenAI Attributes

Exported spans follow the OpenTelemetry GenAI semantic conventions and OpenInference standards:

```json
{
  "name": "gen_ai.chat",
  "attributes": {
    "gen_ai.system": "anthropic",
    "gen_ai.request.model": "claude-3-5-sonnet-20241022",
    "gen_ai.usage.prompt_tokens": 1542,
    "gen_ai.usage.completion_tokens": 384,
    "gen_ai.usage.cost_usd": 0.010386,
    "pa.task_id": "task-1732130000-abcd",
    "pa.objective_id": "OBJ-2026-Q4-SEC",
    "pa.kr_ids": ["KR-SEC-01"]
  }
}
```

---

## 5. Configuration

Settings are declared in `factory.toml` and translated into proxy environment variables by `pa`:

```toml
[telemetry.otlp]
enabled = true
provider = "phoenix"
endpoint = "http://127.0.0.1:4318"
service_name = "pa-factory"
sample_rate = 1.0
scrub_secrets = true
export_prompts = true
```

### Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `OTLP_EXPORTER_ENABLED` | Enables or disables span export. | `true` |
| `OTLP_EXPORTER_ENDPOINT` | HTTP OTLP collector endpoint (`/v1/traces`). | `http://127.0.0.1:4318` |
| `OTLP_EXPORTER_SERVICE_NAME` | Service name stamped on exported spans. | `pa-factory` |
| `OTLP_EXPORTER_SAMPLE_RATE` | Sampling ratio between `0.0` and `1.0`. | `1.0` |
| `OTLP_EXPORTER_SCRUB_SECRETS` | Whether to scrub API keys and auth headers. | `true` |
| `OTLP_EXPORTER_EXPORT_PROMPTS` | Whether to include sanitized prompt text. | `true` |
