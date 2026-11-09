# pa-container

<p align="center">
  <img src="docs/assets/logo.svg" alt="pa-container" width="360">
</p>

A containerized environment for running autonomous coding agents ([Pi](https://pi.dev), [OpenCode](https://github.com/opencode-ai/opencode), [Antigravity](https://antigravity.dev), and [Claude Code](https://claude.com/product/claude-code)) with local large language model (LLM) inference, headless virtual desktop support, and full auditability. A transparent proxy container based on [`mitmproxy`](https://mitmproxy.org) intercepts all HTTP, HTTPS, and DNS traffic from the agent container. It enforces an allowlist and injects secrets when required. It supports macOS, Linux, and WSL2.

<div align="center" style="text-align:center;" markdown="1">

[![CI](https://github.com/mikkovihonen/pa-container/actions/workflows/ci.yml/badge.svg)](https://github.com/mikkovihonen/pa-container/actions/workflows/ci.yml)
[![Coverage](docs/assets/coverage.svg)](docs/development.md#coverage)
[![License: GPLv3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
[![Python: 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/badge/desc/uv-managed-brightgreen.svg)](https://docs.astral.sh/uv/)

</div>

## Highlights

- **Sandboxed agent** — The agent container sends all internet traffic **only** through the proxy. It uses an `--internal` network without a gateway. The system denies all other protocols by default.
- **Auditable traffic** — All HTTP, HTTPS, and DNS traffic is intercepted by [`mitmproxy`](https://mitmproxy.org). It uses a hostname **allowlist** and a **token injector**. It saves the traffic to a flow export file for each project.
- **Multi-agent architecture** — Pluggable agent drivers for [Pi](https://pi.dev), [OpenCode](https://github.com/opencode-ai/opencode), [Antigravity](https://antigravity.dev), and [Claude Code](https://claude.com/product/claude-code) with automatic on-demand toolchain staging and dynamic configuration synthesis across provider formats. See [Multi-Agent Support](docs/agents.md).
- **Local inference** — The `llama-server` tool from [`llama.cpp`](https://llama.app) runs directly on the host computer (Metal / CUDA / ROCm). Multiple projects share it by using a configuration fingerprint.
- **Headless Wayland virtual desktop** — Optional Wayland display stack (`labwc`, `wayvnc`, in-browser `noVNC`, hardware/llvmpipe acceleration) and an in-container `agent-desktop` automation CLI paired with Chrome for Testing (Chromium).
- **Per-workspace isolation** — Each workspace has its own image, proxy, isolated network, mitmweb port, and configuration. The system initializes these items on the first run.
- **Rootless by construction** — It runs on [`podman`](https://podman.io). The agent container runs inside a user namespace where the container root user maps to an unprivileged user on the host. On macOS or Windows, the podman machine requires **at least 4 GB** of memory (`podman machine set --memory 4096`); see [Getting Started](docs/getting-started.md).

## Quick start

```bash
uv run keyring set pa-container ADMIN_PASSWORD  # set mitmweb UI password
./pa build --llama                              # build minimal, optimized llama-server (optional)
./pa build                                      # build the proxy, toolchain and agent images
# Add repo root to PATH or symlink ./pa into ~/.local/bin/pa
cd /path/to/your/project                        # any workspace
pa run                                          # launch the default agent for that workspace
pa run --agent claude                           # or launch another enabled agent (pi, opencode, antigravity, claude)
```

See **[Getting Started](docs/getting-started.md)** for prerequisites, hardware requirements, and platform-specific notes.

## Command-line interface

The unified `pa` CLI manages the full environment lifecycle:

| Subcommand | Description |
|------------|-------------|
| `run` | Launch the containerized coding agent workspace. Supports `--agent`, `--t3`, `--open-browser`, and logging flags. |
| `build` | Compile container images, on-demand toolchains, or local `llama-server`. |
| `clean` | Maintenance utility to sweep dead containers, prune dangling images, and purge logs (`--all`, `--logs`, `--build-cache`). |
| `logs` | Inspect, live-tail (`-f`), filter by subsystem category, or list project session and build logs. |
| `proxy` (`proxies`) | Query active proxy containers, print endpoints (`-u`), output JSON (`--json`), or auto-open mitmweb in the browser (`-o`). |
| `desktop` (`gui`) | Query active virtual desktops, print VNC (`--vnc`) or noVNC (`-u`) URLs, or auto-open noVNC in the browser (`-o`). |
| `init` | Initialize per-project (`pa init`) or global (`pa init --global`) configuration from templates. |

## Documentation

| Page | Contents |
|------|---------------|
| [Getting Started](docs/getting-started.md) | Prerequisites, hardware, platform notes, build & run |
| [Architecture](docs/architecture.md) | Components, network topology, parallel startup orchestration, project structure |
| [Design Details](docs/design-details.md) | Proxy egress policy, nested containers, toolchain builder image |
| [Sandboxing Technologies](docs/sandboxing.md) | Cloud vs. local sandbox paradigms, microVMs, host kernel isolation, and container tradeoffs |
| [Configuration](docs/configuration.md) | Global and per-workspace configuration (allowlist, token replacer, temporary file system, apt dependencies, virtual desktop, logging) |
| [Multi-Agent Support](docs/agents.md) | Pluggable agent architecture (Pi, OpenCode, Antigravity, Claude Code), model synthesis, provider token injection |
| [T3 Code Integration](docs/t3-code.md) | Web UI, remote tunnel access (Tailscale, Cloudflare), and external IP advertising |
| [Development](docs/development.md) | Local dev setup, tests, lint, coverage |
| [Releases](docs/releases.md) | Branch strategy, versioning, and release process |
| [Proxy & addons](docs/proxy/overview.md) | Transparent proxy operation, CA cert, and the [allowlist](docs/proxy/allowlist.md) / [token replacer](docs/proxy/token-replacer.md) / [flow export](docs/proxy/flow-export.md) addons + [addon development guide](docs/proxy/addon-development.md) |

## License

[GPL-3.0](LICENSE)

## Agentic coding disclosure

Built using agentic coding tools.

- [Pi Coding Agent](https://pi.dev) via [pa-container](https://mikkovihonen.github.io/pa-container/) for agentic coding.
- [Claude Code](https://claude.com/product/claude-code)
- [Google Antigravity](https://antigravity.dev)
