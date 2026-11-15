# Getting Started with PA-Container 2.0

PA-Container 2.0 is an Agentic Software Factory that runs autonomous coding agents inside hardware-isolated microVMs with kernel-enforced sandboxes and network auditing.

---

## 1. Prerequisites

Before getting started, ensure your host has the following tools installed:

- **Rust Toolchain:**
    - Stable toolchain (Rust 1.85+) via [rustup](https://rustup.rs):
      ```bash
      curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
      ```
- **Virtualization Hypervisor:**
    - **macOS (Apple Silicon):** Install [Tart](https://tart.run) and initialize the Factory VM:
      ```bash
      # Install Tart
      brew install cirruslabs/cli/tart

      # Create the Factory VM directly from Apple's official IPSW restore image
      tart create pa-factory-macos --from-ipsw latest
      ```
    - **Linux:** Install [Incus](https://linuxcontainers.org/incus/):
      ```bash
      # Debian / Ubuntu (via Zabbly) or Fedora
      sudo apt install incus
      # Ensure non-root user is in the incus-admin group
      sudo usermod -aG incus-admin "$USER"
      newgrp incus-admin
      ```
      The Linux factory VM (`pa-factory-linux`) is automatically provisioned using the latest **Fedora 45** cloud image (`images:fedora/45/cloud`) on `pa factory up`.
- **Python & uv:**
    - Install [uv](https://docs.astral.sh/uv/) (used to run `mitmproxy` and proxy addons):
      ```bash
      curl -LsSf https://astral.sh/uv/install.sh | sh
      ```
- **Git:**
    - Standard Git CLI (version 2.40+) for repository and worktree management.

---

## 2. Quick Setup & Verification

### Clone and Verify Workspace

```bash
git clone https://github.com/mikkovihonen/pa-container.git
cd pa-container

# Build the Rust workspace
cargo build --workspace

# Verify CLI commands
./pa --help
```

### Factory Lifecycle Commands

The `pa factory` command controls the hypervisor microVM lifecycle:

```bash
# Check current factory status
./pa factory status

# Bring up the Factory VM and network bridge
./pa factory up

# Shut down the Factory VM when finished
./pa factory down
```

---

## 3. Running an Agent

To launch an agent inside the factory environment:

```bash
# Launch default agent (agent1) with a prompt
./pa run --agent agent1 --prompt "Implement unit tests for parser module"

# Launch a specific agent driver (e.g. claude, antigravity, or opencode)
./pa run --agent agent2 --prompt "Audit security policies"
```

When you launch an agent:
1. The host CLI synchronizes any uncommitted or committed Git changes to `/var/pa-vault` inside the VM.
2. An isolated POSIX user ($\text{UID} \ge 2001$) is provisioned with a private home and workspace.
3. The in-guest daemon (`pa-agentd`) applies the kernel sandbox (Landlock ABI v4+ on Linux, Seatbelt on macOS).
4. Outbound network traffic is routed transparently through the agent's dedicated Unix Domain Socket (`~/.cache/pa-container/sockets/<agent_id>.sock`).

---

## 4. Multi-Agent Socket Table & Traffic Auditing

PA-Container allocates a distinct Unix Domain Socket for each active agent:

```bash
# View the live proxy routing table
./pa proxy

# Output proxy socket mappings in JSON format
./pa proxy --json

# Open the mitmweb auditing UI in your browser
./pa proxy --open

# Inspect live flow audit logs for an agent
./pa logs --agent agent1
```

Sample output:
```text
AGENT ID        UID      DRIVER     SOCKET PATH                                   ALLOWLIST      
-----------------------------------------------------------------------------------------------
agent1          2001     pi         ~/.cache/pa-container/sockets/agent1.sock      *              
```

---

## 5. Reviewing Agent Changes

All agent changes are recorded in the CoW Git Vault on dedicated branches (`refs/heads/pa/<agent_id>/<task>`). To review changes in an isolated Git worktree:

```bash
# Inspect changes made by agent1
./pa review agent1

# Open the review worktree in your IDE (e.g. VS Code, Cursor, Zed)
./pa review agent1 --open --ide code
```

---

## 6. The Feature Implementation Lifecycle (`pa feature`)

For production feature development, use the structured **Feature Implementation Process**:

```bash
# 1. Interactive Architect interview & specification (Gate 1)
./pa feature plan user-auth

# 2. Inspect status and acceptance criteria
./pa feature status user-auth

# 3. Run the staged Red-Green-Verify pipeline with assertion locking
./pa feature run user-auth

# 4. Review worktree diffs, test logs, and visual evidence (Gate 2)
./pa feature review user-auth

# 5. Approve and merge into main
./pa feature review user-auth --approve
```

See [Feature Implementation Workflow](features.md) for full details on multi-tenant pipelines and assertion locking.
