# Multi-Agent Support

`pa-container` features a decoupled, pluggable agent architecture that allows running multiple coding agent engines within the exact same hardened container sandbox and audit proxy environment.

Whether you run the default **Pi Coding Agent**, **OpenCode**, **Antigravity**, or **Claude Code**, your workspace benefits from:

- **Identical Security Boundary**: Rootless container execution, read-only root filesystem, tmpfs isolation, and egress proxy inspection.
- **Credential Protection**: Agents run with placeholder credentials; actual secrets are stored in the host OS keyring and injected on proxy egress via the Token Replacer addon.
- **Dynamic Model Synthesis**: Host-wide models and gateways (`~/.config/pa-container/models/` and `gateways/`) are translated automatically into native configuration formats for each agent.
- **On-Demand Toolchain Staging**: Alternative agent binaries are built and staged independently as lightweight scratch images and layered into project containers on demand.

---

## Supported Agents

| Agent Identifier | Display Name | Toolchain Package | Default Command | T3 Code Driver |
| :--- | :--- | :--- | :--- | :--- |
| `pi` | Pi Coding Agent | `pi` (`@earendil-works/pi-coding-agent`) | `pi` | `pi` |
| `opencode` | OpenCode | `opencode` (`@opencode/cli`) | `opencode` | — |
| `antigravity` | Google Antigravity | `antigravity` | `antigravity` | — |
| `claude` | Anthropic Claude Code | `claude-code` | `claude` | `claudeAgent` |

---

## Enabling and Selecting Agents

### 1. Workspace Configuration (`config.yaml`)

Specify enabled agents and the default active agent in `.pa-container/config.yaml`. Every agent—including Pi—can be enabled or disabled. At least one agent must be enabled in the configuration:

```yaml
agents:
  # List of agents enabled for this workspace (at least one required).
  # Supported: pi, opencode, antigravity, claude
  enabled:
    - pi
    - opencode
  # Default active agent when --agent is omitted on the CLI.
  default: pi

agent:
  command: ["run"]       # Optional command arguments override
  options: ["--verbose"] # Optional CLI options appended to invocation
```

When configured in `config.yaml`, `pa-container` automatically builds and includes the toolchains for all enabled agents in the project container image and sets up the appropriate state directories and mounts.

### 2. Command-Line Override (`--agent`)

You can select any enabled agent for a single invocation using the `--agent` command-line flag:

```bash
# Launch OpenCode in interactive mode (must be in agents.enabled)
./run.sh --agent opencode

# Launch Google Antigravity (must be in agents.enabled)
./run.sh --agent antigravity

# Launch Claude Code (must be in agents.enabled)
./run.sh --agent claude
```

If an agent is not listed in `agents.enabled`, `pa-container` rejects the invocation with an error.

---

## Agent Architectures & Isolation

### 1. Pi Coding Agent (`pi`)

- **State Directory**: `.pa-container/agents/pi/` mounted to `/home/agent/.pi/agent`.
- **Configuration**: Synthesizes native `/home/agent/.pi/agent/models.json` on-demand from host models and project allowlist.
- **Tmpfs Isolation**: Transient binaries in `/home/agent/.pi/agent/bin` are mounted on tmpfs to prevent disk persistence.

### 2. OpenCode (`opencode`)

- **State Directory**: `.pa-container/agents/opencode/` mounted to `/home/agent/.config/opencode`.
- **Model Translation**: Synthesizes `.pa-container/agents/opencode/config.json` with OpenAI-compatible endpoint configurations.
- **Egress Authentication**: Outgoing requests carry placeholder `Bearer pa-container-token-placeholder` headers that the proxy transforms into the real API key.

### 3. Google Antigravity (`antigravity`)

- **State Directory**: `.pa-container/agents/antigravity/` mounted to `/home/agent/.gemini/antigravity`.
- **Model Translation**: Synthesizes `.pa-container/agents/antigravity/config.json` targeting Gemini models.
- **Egress Authentication**: Proxy injects the host's `GEMINI_API_KEY` into `x-goog-api-key` headers for `generativelanguage.googleapis.com`.

### 4. Claude Code (`claude`)

- **State Directory**: `.pa-container/agents/claude/` mounted to `/home/agent/.claude`.
- **Model Translation**: Synthesizes `.pa-container/agents/claude/claude.json`.
- **Egress Authentication**: Outgoing requests carry `x-api-key: pa-container-token-placeholder` replaced with the host's `ANTHROPIC_API_KEY`.
- **T3 Code Integration**: Enables the `claudeAgent` provider in T3 Code for web-based multi-agent workflows.

---

## Dynamic Model Synthesis

Instead of managing separate configuration formats for each agent, `pa-container` synthesizes native configuration files dynamically from your global models and an optional project-level allowlist.

### Global Models & Gateways

Global model definitions reside on your host:
- `~/.config/pa-container/models/*.yaml`: Local LLM endpoints (llama.cpp, Ollama, vLLM).
- `~/.config/pa-container/gateways/*.yaml`: Remote gateways (OpenAI, Anthropic, Opper, OpenRouter).

### Project Allowlist (`.pa-container/models.yaml`)

You can restrict which models are available to the agent in your project workspace by creating `.pa-container/models.yaml`:

```yaml
# Optional default model to set as active
default: "claude-3-7-sonnet"

# Allowlist of model or gateway names permitted in this project
allow:
  - "claude-3-7-sonnet"
  - "qwen-2.5-coder-32b"
  - "opper"
```

---

## On-Demand Toolchain Staging

Agent toolchains are packaged as independent recipes in `coding-agent-builder/tools/`:

- `coding-agent-builder/tools/opencode/build.sh`
- `coding-agent-builder/tools/antigravity/build.sh`
- `coding-agent-builder/tools/claude-code/build.sh`

Each recipe verifies SHA256 checksums across both `amd64` and `arm64` architectures and exports a standalone scratch stage (`stage-<tool>`).

When an agent is selected:
1. `pa-container` checks if the tool image `localhost/pa-container-agent-tool-<agent>:local` exists and matches the content hash of the recipe.
2. If absent or stale, the tool image is built in seconds.
3. The tool image is layered into the project-specific agent container image via build-contexts (`--build-context tool_<agent>=docker-image://...`).

---

## Adding Custom Agent Drivers

New agents can be integrated into `pa-container` by creating a new `AgentDriver` subclass:

1. Create a driver class inheriting from `agents.base.AgentDriver`:
    - Implement `name`, `required_tools`, `get_mounts()`, `get_command()`, and `synthesize_config()`.
2. Register the driver in `src/agents/__init__.py`:
    - Add the class to `_DRIVERS`.
3. Add the packaging recipe in `coding-agent-builder/tools/<tool>/build.sh`.
4. Register the tool in `src/toolchains.py`:
    - Add tool identifier to `ON_DEMAND_TOOLS`.
