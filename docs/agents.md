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
pa run --agent opencode

# Launch Google Antigravity (must be in agents.enabled)
pa run --agent antigravity

# Launch Claude Code (must be in agents.enabled)
pa run --agent claude
```

If an agent is not listed in `agents.enabled`, `pa-container` rejects the invocation with an error.

---

## Agent Architectures & Isolation

### 1. Pi Coding Agent (`pi`)

- **State Directory**: `.pa-container/agents/pi/` mounted to `/home/agent/.pi/agent`.
- **Configuration**: Synthesizes native `/home/agent/.pi/agent/models.json` on-demand from host models and project allowlist.
- **Tmpfs Isolation**: Transient binaries in `/home/agent/.pi/agent/bin` are mounted on tmpfs to prevent disk persistence.

### 2. OpenCode (`opencode`)

- **State Directory**: `.pa-container/agents/opencode/` mounted to `/home/agent/.config/opencode` (configuration) and `.pa-container/agents/opencode/data/` mounted to `/home/agent/.local/share/opencode` (sessions and database).
- **Model Translation**: Synthesizes `.pa-container/agents/opencode/opencode.json` with OpenAI-compatible endpoint configurations and restricts `enabled_providers` to project-configured models.
- **Egress Authentication**: Outgoing requests carry placeholder `Bearer pa-container-token-placeholder` headers that the proxy transforms into the real API key.

### 3. Google Antigravity (`antigravity`)

- **State Directory**: `.pa-container/agents/antigravity/` mounted to `/home/agent/.gemini/antigravity` (and `.pa-container/agents/antigravity/config/` mounted to `/home/agent/.gemini/config`).
- **Model Translation**: Synthesizes `.pa-container/agents/antigravity/config.json` and `settings.json` targeting Gemini models.
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

## Agent Capability Packages (ACPs)

Agent runtimes are packaged as independent Agent Capability Packages in `packages/`:

- `packages/opencode/package.yaml`
- `packages/antigravity/package.yaml`
- `packages/claude-code/package.yaml`
- `packages/pi/package.yaml`

Each package defines its binary payloads, skills (`skill/SKILL.md`), MCP server configurations, egress allowlists, and verification commands.

When an agent is selected:
1. `pa-container` checks if the capability image `pa-container-pkg-<agent>:local` exists and matches the content hash of the package directory.
2. If absent or stale, the package image is built automatically.
3. The package image is dynamically composed into the project-specific agent container image via `COPY --from=pa-container-pkg-<agent>:local / /`.

---

## Adding Custom Agent Drivers

New agents can be integrated into `pa-container` by creating a new `AgentDriver` subclass:

1. Create a driver class inheriting from `agents.base.AgentDriver`:
    - Implement `name`, `required_packages`, `get_mounts()`, `get_command()`, and `synthesize_config()`.
2. Register the driver in `src/agents/__init__.py`:
    - Add the class to `_DRIVERS`.
3. Add the capability package in `packages/<pkg>/package.yaml` and `packages/<pkg>/skill/SKILL.md`.
