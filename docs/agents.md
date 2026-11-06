# Multi-Agent Support

`pi-container` features a decoupled, pluggable agent architecture that allows running multiple coding agent engines within the exact same hardened container sandbox and audit proxy environment.

Whether you run the default **Pi Coding Agent**, **OpenCode**, **Antigravity**, or **Claude Code**, your workspace benefits from:

- **Identical Security Boundary**: Rootless container execution, read-only root filesystem, tmpfs isolation, and egress proxy inspection.
- **Credential Protection**: Agents run with placeholder credentials; actual secrets are stored in the host OS keyring and injected on proxy egress via the Token Replacer addon.
- **Dynamic Model Synthesis**: Host-wide models and gateways (`~/.config/pi-container/models/` and `gateways/`) are translated automatically into native configuration formats for each agent.
- **On-Demand Toolchain Staging**: Alternative agent binaries are built and staged independently as lightweight scratch images and layered into project containers on demand.

---

## Supported Agents

| Agent Identifier | Display Name | Toolchain Package | Default Command | T3 Code Driver |
| :--- | :--- | :--- | :--- | :--- |
| `pi` *(default)* | Pi Coding Agent | Built into base image | `pi` | `pi` |
| `opencode` | OpenCode | `opencode` (`@opencode/cli`) | `opencode` | — |
| `antigravity` | Google Antigravity | `antigravity` | `antigravity` | — |
| `claude` | Anthropic Claude Code | `claude-code` | `claude` | `claudeAgent` |

---

## Selecting an Agent

### 1. Project Configuration (`config.yaml`)

Specify the desired agent runtime in `.pi-container/config.yaml`:

```yaml
agent:
  type: opencode         # pi (default) | opencode | antigravity | claude
  command: ["run"]       # Optional command arguments override
  options: ["--verbose"] # Optional CLI options appended to invocation
```

When configured in `config.yaml`, `pi-container` automatically includes any required staging tools in the project container image and sets up the appropriate mounts.

### 2. Command-Line Override (`--agent`)

You can override the project agent configuration for a single invocation using the `--agent` command-line flag:

```bash
# Launch OpenCode in interactive mode
uv run pi-container run --agent opencode

# Launch Google Antigravity
uv run pi-container run --agent antigravity

# Launch Claude Code
uv run pi-container run --agent claude
```

---

## Agent Architectures & Isolation

### 1. Pi Coding Agent (`pi`)

- **State Directory**: `.pi-container/agent/` mounted to `/home/pi/.pi/agent`.
- **Configuration**: Uses `.pi-container/agent/models.json` or synthesizes configuration from host models.
- **Tmpfs Isolation**: Transient binaries in `/home/pi/.pi/agent/bin` are mounted on tmpfs to prevent disk persistence.

### 2. OpenCode (`opencode`)

- **State Directory**: `.pi-container/agents/opencode/` mounted to `/home/pi/.config/opencode`.
- **Model Translation**: Synthesizes `.pi-container/agents/opencode/config.json` with OpenAI-compatible endpoint configurations.
- **Egress Authentication**: Outgoing requests carry placeholder `Bearer pi-container-token-placeholder` headers that the proxy transforms into the real API key.

### 3. Google Antigravity (`antigravity`)

- **State Directory**: `.pi-container/agents/antigravity/` mounted to `/home/pi/.gemini/antigravity`.
- **Model Translation**: Synthesizes `.pi-container/agents/antigravity/config.json` targeting Gemini models.
- **Egress Authentication**: Proxy injects the host's `GEMINI_API_KEY` into `x-goog-api-key` headers for `generativelanguage.googleapis.com`.

### 4. Claude Code (`claude`)

- **State Directory**: `.pi-container/agents/claude/` mounted to `/home/pi/.claude`.
- **Model Translation**: Synthesizes `.pi-container/agents/claude/claude.json`.
- **Egress Authentication**: Outgoing requests carry `x-api-key: pi-container-token-placeholder` replaced with the host's `ANTHROPIC_API_KEY`.
- **T3 Code Integration**: Enables the `claudeAgent` provider in T3 Code for web-based multi-agent workflows.

---

## Dynamic Model Synthesis

Instead of managing separate configuration formats for each agent, `pi-container` synthesizes native configuration files dynamically from your global models and an optional project-level allowlist.

### Global Models & Gateways

Global model definitions reside on your host:
- `~/.config/pi-container/models/*.yaml`: Local LLM endpoints (llama.cpp, Ollama, vLLM).
- `~/.config/pi-container/gateways/*.yaml`: Remote gateways (OpenAI, Anthropic, Opper, OpenRouter).

### Project Allowlist (`.pi-container/models.yaml`)

You can restrict which models are available to the agent in your project workspace by creating `.pi-container/models.yaml`:

```yaml
# Optional list of model names permitted in this project
models:
  - "claude-3-7-sonnet"
  - "qwen-2.5-coder-32b"
  - "opper"

# Optional default model to set as active
default_model: "claude-3-7-sonnet"
```

If `.pi-container/models.yaml` is absent, all valid global models and gateways are made available to the agent.

---

## On-Demand Toolchain Staging

Agent toolchains are packaged as independent recipes in `coding-agent-builder/tools/`:

- `coding-agent-builder/tools/opencode/build.sh`
- `coding-agent-builder/tools/antigravity/build.sh`
- `coding-agent-builder/tools/claude-code/build.sh`

Each recipe verifies SHA256 checksums across both `amd64` and `arm64` architectures and exports a standalone scratch stage (`stage-<tool>`).

When an agent is selected:
1. `pi-container` checks if the tool image `localhost/pi-coding-agent-tool-<agent>:local` exists and matches the content hash of the recipe.
2. If absent or stale, the tool image is built in seconds.
3. The tool image is layered into the project-specific agent container image via build-contexts (`--build-context tool_<agent>=docker-image://...`).

---

## Adding Custom Agent Drivers

New agents can be integrated into `pi-container` by creating a new `AgentDriver` subclass:

1. Create a driver class inheriting from `agents.base.AgentDriver`:
    - Implement `name`, `required_tools`, `get_mounts()`, `get_command()`, and `synthesize_config()`.
2. Register the driver in `src/agents/__init__.py`:
    - Add the class to `_DRIVERS`.
3. Add the packaging recipe in `coding-agent-builder/tools/<tool>/build.sh`.
4. Register the tool in `src/toolchains.py`:
    - Add tool identifier to `ON_DEMAND_TOOLS`.
