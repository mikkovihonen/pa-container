# Opper AI Gateway Setup

This setup connects `pa-container` to [Opper AI](https://platform.opper.ai/) via its European-hosted OpenAI-compatible Chat Completions endpoint (`https://api.opper.ai/v3/compat`).

---

## Prerequisites

1. An Opper account and API key from [platform.opper.ai](https://platform.opper.ai/) under **Settings > API keys**.
2. Store your API key in your OS user keyring:
```bash
uv run keyring set pa-container OPPER_API_KEY
```

---

## Configuration Steps

### 1. Configure the Gateway Definition
Copy `opper.yaml` from this directory into `~/.config/pa-container/gateways/opper.yaml`:
```bash
mkdir -p ~/.config/pa-container/gateways
cp docs/setups/opper/opper.yaml ~/.config/pa-container/gateways/
```

### 2. Configure the Workspace Models Allowlist
Add `opper` to `.pa-container/models.yaml` under `allow`:
```yaml
allow:
  - "opper"
```

### 3. Allow Proxy Egress
Add `api.opper.ai` to your workspace `.pa-container/allowlist.yaml`:
```yaml
    - name: "opper-ai-allow"
      mode: "allow"
      hostnames:
        - "api.opper.ai"
      ip_ranges: []
```

### 4. Configure Credential Injection
Add the following rule to `.pa-container/token_replacer.yaml`:
```yaml
rules:
  - name: "Inject Opper API Key"
    hostnames:
      - "api.opper.ai"
    content_patterns:
      - field: "headers"
        header_name: "Authorization"
        regex: "(?<=Bearer\\s)OPPER_API_KEY_PLACEHOLDER"
    replace_with:
      strategy: "static"
      value: "${ENV:OPPER_API_KEY}"
```

---

## Notes & Features

- **Zero Secret Exposure:** The agent container only sees the dummy token `OPPER_API_KEY_PLACEHOLDER`. Real credentials never enter the agent container.
- **Failover Pools & Bare Model Names:**
    - Using provider prefixes like `anthropic/claude-sonnet-4-6` pins the route to Anthropic.
    - Using bare model names like `claude-sonnet-4-6` activates Opper's dynamic multi-provider routing and automatic failover.
- **EU Data Sovereignty & Zero Data Retention:**
    - Opper supports EU-only inference hosting and Zero Data Retention (ZDR) configurable in the Opper platform dashboard.

