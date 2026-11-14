# Configuration Reference: PA-Container 2.0

PA-Container 2.0 uses declarative TOML configurations for both factory VM orchestration (`factory.toml`) and modular capability packs (`capability.toml`).

---

## 1. Factory Configuration (`factory.toml`)

The root `factory.toml` file declares the multi-agent topology, hypervisor backend settings, and network proxy rules for the software factory.

### Schema Version 2.0 Specification

```toml
schema_version = "2.0"

[factory]
# Hypervisor backend: "auto", "macos-tart", "linux-incus", or "linux-cloud"
backend = "auto"
vm_name = "pa-factory-vm"
cpus = 4
memory_mb = 8192
disk_gb = 50

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
- **`backend`**: Hypervisor orchestration engine. Defaults to `"auto"`, which detects Tart on macOS Apple Silicon and Incus on Linux.
- **`vm_name`**: Name of the target microVM instance.
- **`cpus`**: Number of virtual CPU cores allocated to the factory VM.
- **`memory_mb`**: RAM allocated in megabytes (minimum 4096 recommended).
- **`disk_gb`**: Disk size in gigabytes.

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
- **`[env]`**:
    - Environment variables injected into the agent's sandboxed execution environment.
- **`[proxy]`**:
    - **`allowlist`**: Outbound hostnames permitted when this pack is attached to an agent.
    - **`[[proxy.tokens]]`**: Scopes token injection so secrets are only injected to authorized target hosts.
