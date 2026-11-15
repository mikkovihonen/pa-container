# Configuration Reference: PA-Container 2.0

PA-Container 2.0 uses declarative TOML configurations for both factory VM orchestration (`factory.toml`) and modular capability packs (`capability.toml`).

---

## 1. Factory Configuration (`factory.toml`)

The root `factory.toml` file declares the multi-agent topology, hypervisor backend settings, and network proxy rules for the software factory.

### Schema Version 2.0 Specification

```toml
schema_version = "2.0"

[factory]
name = "pa-factory"
description = "Software Factory VM for multi-agent workflows"

[compute]
# Hypervisor backend: "auto", "macos-tart", "linux-incus", or "linux-cloud"
backend = "auto"
cpus = 8
memory_mb = 16384
gpu = "optional"

[compute.metal]
# Explicit opt-in for macOS Apple Silicon paravirtualized Metal capabilities
enabled = true
# Host preference lifecycle: "ephemeral" (default, reverts on factory down), "persistent", or "none"
host_mode = "ephemeral"
# Target Apple GPU family ceiling (1001-1999, default 1009 = Apple Family 9 / M3/M4)
apple_family_max = 1009
# Threadgroup memory floor in bytes (default 65536 = 64 KiB)
max_threadgroup_memory = 65536

[proxy]
base_proxy_port = 8081
base_transparent_port = 8091
dns_port = 5353
default_allowlist = ["github.com", "pypi.org", "registry.npmjs.org"]

[git]
default_branch = "main"
vault_path = "/var/pa-vault"
branch_pattern = "refs/heads/pa/{agent_id}/*"

[[agents]]
id = "agent1"
uid = 2001
driver = "pi"
capabilities = ["git", "source-control", "image-tools"]
allowlist = ["api.openai.com", "generativelanguage.googleapis.com"]
tokens = ["OPENAI_API_KEY", "GEMINI_API_KEY"]

[[agents]]
id = "agent2"
uid = 2002
driver = "claude"
capabilities = ["git", "source-control", "document-tools"]
allowlist = ["api.anthropic.com"]
tokens = ["ANTHROPIC_API_KEY"]
```

### Configuration Sections

#### `[factory]`
- **`name`**: Descriptive label for the software factory.
- **`description`**: Optional textual description.

#### `[compute]`
- **`backend`**: Hypervisor orchestration engine. Defaults to `"auto"`, which detects Tart on macOS Apple Silicon and Incus on Linux.
- **`cpus`**: Number of virtual CPU cores allocated to the factory VM.
- **`memory_mb`**: RAM allocated in megabytes (minimum 4096 recommended).
- **`gpu`**: GPU allocation policy (`"optional"`, `"required"`, or `"disabled"`).

#### `[compute.metal]`
- **`enabled`**: Explicit opt-in boolean (defaults to `false`). When `false`, zero host preferences are touched and guest processes run stock virtual graphics.
- **`host_mode`**: Host hypervisor preference lifecycle:
    - `"ephemeral"` *(Default)*: Automatically sets `defaults write com.apple.gpusw.ParavirtualizedGraphics ForceUnrestrictedDeviceFeatureLevel -bool true` on the host prior to Tart execution, and cleanly deletes it upon factory teardown (`pa factory down`). Leaves zero persistent host changes.
    - `"persistent"`: Sets the host preference permanently.
    - `"none"`: Never modifies host settings (assumes external out-of-band management).
- **`apple_family_max`**: Maximum Apple GPU feature tier to expose via the interposer shim (defaults to `1009` for Apple Family 9 / M3/M4).
- **`max_threadgroup_memory`**: Memory ceiling in bytes (defaults to `65536` for 64 KiB, overcoming stock 32 KiB restriction).

#### `[proxy]`
- **`base_proxy_port`**: Starting port number for dedicated agent HTTP/HTTPS proxy listeners (defaults to `8081`).
- **`base_transparent_port`**: Starting port number for transparent egress redirection (defaults to `8091`).
- **`dns_port`**: Internal DNS resolver port (defaults to `5353`).
- **`default_allowlist`**: Hostnames universally reachable across all agents.

#### `[[agents]]`
- **`id`**: Unique string identifier for the agent (e.g. `agent1`, `lead-architect`).
- **`uid`**: POSIX user identifier assigned inside the VM (must be $\ge 2001$).
- **`driver`**: Supported agent runner (`pi`, `claude`, `opencode`, `antigravity`).
- **`capabilities`**: List of capability packs mounted into the agent's environment.
- **`allowlist`**: Agent-specific destination domains permitted through the proxy.
- **`tokens`**: Environment variables subject to HMAC placeholder generation and dynamic proxy secret injection.

---

## 2. Capability Manifest (`capability.toml`)

Every directory under `pa_packages/capabilities/`, `pa_packages/toolchains/`, and `pa_packages/agents/` defines a self-contained capability manifest.

### Schema Version 1.0 Specification

```toml
schema_version = "1.0"

[capability]
name = "image-tools"
category = "media"
version = "1.0.0"
description = "Image processing capability: ImageMagick conversion, ExifTool metadata, WebP/JPEG/PNG utilities"
requires = []

[staging]
install_prefix = "/opt/pa/packs/image-tools"
bin_dirs = ["bin"]

[env]
MAGICK_MEMORY_LIMIT = "1GiB"

[proxy]
allowlist = ["api.stability.ai"]

[[proxy.tokens]]
env_var = "STABILITY_API_KEY"
allowed_hosts = ["api.stability.ai"]
```

### Manifest Fields

- **`[capability]`**:
    - **`name`**: Unique identifier of the pack.
    - **`category`**: Semantic classification (`media`, `devtools`, `cloud`, `browser`, `desktop`, etc.).
    - **`requires`**: Ordered list of prerequisite capability packs resolved topologically.
- **`[staging]`**:
    - **`install_prefix`**: Filesystem destination inside the VM.
    - **`bin_dirs`**: Subdirectories appended to the agent's `$PATH`.
    - **`fedora_packages`**: Native Fedora packages provisioned dynamically in guest Linux VMs via `dnf install -y`.
    - **`macos_brew_packages`**: Native Homebrew packages provisioned dynamically in guest macOS VMs via `brew install`.
- **`[entitlements]`**:
    - **`read_paths`**: Additional filesystem read paths granted in Seatbelt profiles or Bubblewrap mounts.
    - **`write_paths`**: Additional filesystem write paths granted in Seatbelt profiles or Bubblewrap mounts.
    - **`allow_gpu`**: Enables hardware compute access (Metal/CoreML IOKit on macOS, `/dev/dri` and compute nodes on Linux).
    - **`allow_network_bind`**: Local TCP ports the agent sandbox is permitted to bind.
- **`[env]`**:
    - Environment variables injected into the agent's sandboxed execution environment.
- **`[proxy]`**:
    - **`allowlist`**: Outbound hostnames permitted when this pack is attached to an agent.
    - **`[[proxy.tokens]]`**: Scopes token injection so secrets are only injected to authorized target hosts.
