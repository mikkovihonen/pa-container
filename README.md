# PA-Container 2.0: Next-Generation Agentic Software Factory

<p align="center">
  <img src="docs/assets/pa-container-logo.svg" alt="pa-container logo" width="360">
</p>

PA-Container 2.0 is a multi-agent **Agentic Software Factory** environment built in Rust. It isolates autonomous coding agents ([Pi](https://pi.dev), [OpenCode](https://github.com/opencode-ai/opencode), [Antigravity](https://antigravity.dev), and [Claude Code](https://claude.com/product/claude-code)) inside hardware-isolated microVMs (Tart on macOS Apple Silicon, Incus on Linux).

Agents run as distinct unprivileged POSIX users ($\text{UID} \ge 2001$) confined by native kernel sandboxes (Landlock ABI v4+ on Linux, Seatbelt on macOS) and a multi-port egress proxy that strictly enforces per-agent host allowlists and zero-knowledge secret token injection.

<div align="center" style="text-align:center;" markdown="1">

[![CI](https://github.com/mikkovihonen/pa-container/actions/workflows/ci.yml/badge.svg)](https://github.com/mikkovihonen/pa-container/actions/workflows/ci.yml)
[![License: GPLv3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
[![Rust: 1.85+](https://img.shields.io/badge/rust-1.85%2B-orange.svg)](https://www.rust-lang.org/)
[![uv](https://img.shields.io/badge/desc/uv-managed-brightgreen.svg)](https://docs.astral.sh/uv/)

</div>

---

## Key Highlights

- **Hardware MicroVM Boundary:**
    - macOS: Automated orchestration via Tart virtualization and Softnet network bridge.
    - Linux: Automated orchestration via Incus system containers and microVMs.
- **In-Guest Daemon (`pa-agentd`):**
    - High-performance, static Rust control plane communicating over JSON-RPC 2.0 stdio.
    - Manages POSIX multi-tenant agent users ($\text{UID} \ge 2001$) with isolated homes and cgroups.
- **Dual-Layer Sandbox Security:**
    - Linux: Native Rust Landlock ABI v4+ restricting filesystem and network syscalls, paired with Bubblewrap.
    - macOS: Dynamic Seatbelt profile compilation (`sandbox-exec`) with entitlement access to Apple Silicon Metal/ANE.
- **CoW Git Vault & Worktree Isolation:**
    - Host dirty trees are ingested into bare repositories at `/var/pa-vault` with Copy-on-Write branches.
    - Pure POSIX pre-receive hooks enforce agent branch isolation (`refs/heads/pa/$AGENT_ID/*`).
- **Multi-Port Auditable Proxy (`coding-agent-proxy`):**
    - Mitmproxy intercepts traffic across dedicated per-agent ports (`8081`, `8082`, ...).
    - Enforces declarative host allowlists and dynamically replaces HMAC placeholder tokens with real secrets.
- **Declarative Capability Packs:**
    - Unified `capability.toml` manifests define tools, dependencies, and network egress rules without legacy container layering.

---

## Quick Start

### 1. Prerequisites

- **macOS:** Apple Silicon (M1/M2/M3/M4) with macOS 13+, Xcode Command Line Tools, and [Tart](https://tart.run).
- **Linux:** Kernel 6.7+ (with Landlock ABI v4+ support) and [Incus](https://linuxcontainers.org/incus/).
- **Rust:** Stable toolchain (`cargo`, `rustc` 1.85+).
- **Python / uv:** Python 3.14 managed via `uv` for the egress proxy.

### 2. Basic Usage

```bash
# Clone the repository
git clone https://github.com/mikkovihonen/pa-container.git
cd pa-container

# Check CLI commands
./pa --help

# Inspect multi-agent proxy port assignments and policies
./pa proxy

# Start the factory environment and launch an agent
./pa run --agent agent1 --prompt "Refactor error handling in parser.rs"

# Review changes made by an agent in an isolated Git worktree
./pa review agent1 --open

# Check factory lifecycle status
./pa factory status
```

---

## Workspace Layout

```
pa-container/
├── Cargo.toml                  # Workspace root (pa-core, pa-cli, pa-agentd, pa-landlock)
├── crates/
│   ├── pa-core/                # Schemas, backends (Tart/Incus), Git vault, and sandboxes
│   ├── pa-cli/                 # Unified host CLI binary (`pa`)
│   ├── pa-agentd/              # Static in-guest daemon & iOS Simulator bridge
│   └── pa-landlock/            # Native Linux Landlock ABI v4+ sandbox restrictor
├── coding-agent-proxy/         # Mitmproxy stack (allowlist, token replacer, flow export)
├── defaults/                   # Default configs, chat templates, and model definitions
├── vm-images/                  # Guest VM provisioning templates (macOS Tart, Fedora Incus)
└── pa_packages/                # Declarative capability packages
    ├── agents/                 # Pluggable agent drivers (Pi, Claude, OpenCode, Antigravity)
    ├── toolchains/             # Language toolchains (Rust, Python, Node, Go)
    └── capabilities/           # Composable capability packs (Media, Desktop, iOS, Git, etc.)
```

---

## License

PA-Container is licensed under the [GNU General Public License v3.0](LICENSE).
