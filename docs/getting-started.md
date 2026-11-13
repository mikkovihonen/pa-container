# Getting Started

## Prerequisites

Install the following tools on your host machine before running:

- **[uv](https://docs.astral.sh/uv/)**: Manages the Python environment and dependencies for the host-side build and run CLI.
    - On macOS: `brew install uv`
    - Other platforms: `curl -LsSf https://astral.sh/uv/install.sh | sh`
    - `pa` invokes `uv run`. The `uv run` command creates `.venv` and installs the declared dependencies (including the `hf` CLI and `huggingface_hub`) automatically on first use. You do not need a manual `pip install`.

- **[podman](https://podman.io)**: the only supported container runtime.
    - On macOS: `brew install podman`, then **`podman machine init --memory 4096`** and `podman machine start`
    - On Linux: `sudo dnf install podman` (Fedora/RHEL) or `sudo apt install podman` (Debian/Ubuntu), or your distro's package manager

  **The podman machine needs at least 4 GB of memory** (macOS/Windows, where podman
  runs in a VM). The default is 2 GiB, which is not enough. `pa build` compiles CPython,
  podman and netavark from source, and one CPython PGO job peaks near 900 MiB. With
  2 GiB total, the build is OOM-killed. More memory buys more parallel compile
  jobs, since the caps are memory-derived rather than core-count-derived. On an existing
  machine:

  ```bash
  podman machine stop && podman machine set --memory 4096 && podman machine start
  ```

  `pa build` checks this before it starts building and tells you if there is not
  enough room, so a short machine fails in a second rather than several minutes in.

  Docker is **not** supported. pa-container's isolation model (and nested containers in
  particular) depends on the agent container running inside a user namespace where
  container uid 0 maps to an unprivileged host user. Stock Docker does not provide this.
  See [Configuration](configuration.md#nested-containers).

- **llama.cpp**: Specifically `llama-server`.
    - Build with pa-container (recommended): `pa build --llama` (or `pa build --llama-latest` to build latest release)
    - On macOS: `brew install llama.cpp`
    - On Linux: `sudo dnf install llama.cpp` (Fedora/RHEL) or `sudo apt install llama.cpp` (Debian/Ubuntu)
    - On Linux (other): [build from source](https://github.com/ggml-org/llama.cpp)
    - On WSL2: `sudo dnf install llama.cpp` (Fedora/WSL) or `sudo apt install llama.cpp` (Ubuntu/Debian WSL)

You declare Python dependencies (`huggingface_hub[cli]`, `pyyaml`) in
`pyproject.toml`. `uv` installs them. You do not install them manually.

## Hardware Requirements

Use the following hardware to run this environment comfortably, especially with the full 128k context window:

- **Processor:**
    - Apple Silicon (M2-series Max/Ultra or above) for high memory bandwidth.
    - On Linux/WSL2: A modern multi-core CPU with AVX2 support.
- **Memory (RAM):**
    - **Minimum:** 32 GB (Performance may degrade with large contexts).
    - **Recommended:** 64 GB or more (For optimal performance).
- **podman machine (macOS/Windows):**
    - **Required:** 4 GB (`podman machine set --memory 4096`). The 2 GiB default cannot build the toolchain image.
    - **Recommended:** 8 GB, and more again if you enable [nested containers](configuration.md#nested-containers).
- **Storage:** 50 GB of available SSD space.

## Platform-Specific Notes

### Linux / WSL2

- **Container runtime**: podman (auto-detected).
- **Network**: The proxy upstream network defaults to `podman` (configured via `runtime.proxy_upstream_network` in `~/.config/pa-container/config.yaml`).
- **LLaMA backend**: The `llama-server` binary runs natively on Linux/WSL2. For GPU acceleration on Linux, build llama.cpp with CUDA or ROCm support.
- **WSL2**: Ensure WSL2 is properly configured with a Linux distro. podman runs inside it.

### macOS

- **Container runtime**: podman.
- **Network**: The defaults apply automatically.
- **LLaMA backend**: Runs natively using Apple's Metal GPU acceleration.
- **podman on macOS**: containers run inside a Linux VM (no `podman0` bridge exists on the host). The system does not use `socat`. The proxy reaches host `llama-server` via `host.containers.internal` (gvproxy). The isolated network is created `--internal --disable-dns`. The proxy's interfaces are pinned (`interface_name=eth0` / `interface_name=eth1`) so the isolated network is deterministically `eth1`. See [`pa_core/runtimes.py`](https://github.com/mikkovihonen/pa-container/blob/main/pa_core/runtimes.py).
- **Machine sizing**: **4 GB is the minimum** (`podman machine set --memory 4096`). The 2 GiB default cannot build the toolchain image. `resources.agent.memory` defaults to `16g`, which the VM can never actually provide. Raise the machine further before enabling [nested containers](configuration.md#nested-containers). Do this especially before `storage: tmpfs`.

## Build and Run

### 1. Configure Environment

pa-container automatically seeds its global configuration at `~/.config/pa-container/config.yaml` on first launch.

Set **`ADMIN_PASSWORD`** in your OS keyring before running — the proxy's mitmweb UI requires a password:

```bash
uv run keyring set pa-container ADMIN_PASSWORD
```

Optionally, build an optimized minimal `llama-server` binary for your host hardware:

```bash
pa build --llama
```

See [Configuration](configuration.md) for the full list of configuration options.

### 2. Build the Container Images

```zsh
pa build
```

`pa` runs through `uv`. `uv` creates the `.venv` and installs dependencies from `uv.lock` on first invocation. You do not need a separate setup step. Run `uv sync` to provision the environment ahead of time.

This builds the shared container images:

1. `pa-container-agent-proxy:local` — the transparent proxy built from Fedora Minimal, which includes mitmproxy and shares the Python ACP package layer.
2. `pa-container-agent:local` — the shared agent runner built from Fedora Minimal, dynamically composed with core ACP package layers (Python 3.15 with `uv`, Node.js 26, rootless Podman 6, Netavark/Aardvark-dns).

Individual packages can be built or updated on demand with `pa build --packages <name>` (or `pa build --packages all`). Every package manifest in `pa_packages/<name>/package.yaml` declares its own version, platform download hashes, skills, and configuration.

### 3. Run the Agent

The `pa run` command manages the entire lifecycle. It validates the environment, starts llama-server instances for each local model allowed in `models.yaml`, sets up the proxy container with its transparent proxy rules, and launches the agent container.

```sh
# Add repo root to PATH or symlink ./pa into ~/.local/bin/pa
cd /path/to/your/project

# Launch the default agent workspace
pa run

# Or launch with custom arguments (e.g. forward session flags to inner agent)
pa run -- --session 1234abcd-ef56-78ab-cd90-1234abcd56ef
```

The script reads `<project>/.pa-container/models.yaml` (seeded from the `coding-agent/default/project/` template on first run) to determine which LLM providers and gateways are allowed. Global definitions under `~/.config/pa-container/models/` and `~/.config/pa-container/gateways/` supply model weights, server flags, and gateway endpoints. Each workspace gets its own proxy container and isolated network (named by a hash of the project path). Concurrent invocations **from the same workspace** share that workspace's proxy via a refcount.

### 4. Using the Agent

Once the server is ready, you can interact with the agent through the terminal. The current directory is mounted to `/workspace` inside the container, allowing the agent to read and write files in your project.

The agent's entrypoint runs project-specific setup scripts (baked into the image at build time), points the container's default route and DNS at the proxy, and applies the host's git config. Reaching the host `llama-server` is handled by the proxy (via `host.containers.internal` on macOS or directly on Linux). See [Architecture](architecture.md) and [Dependency definition files](configuration.md#dependency-definition-files).

### 5. Using the Proxy

The transparent proxy web UI (mitmweb) is published on an auto-assigned host port — run.py logs the exact `http://127.0.0.1:<port>` URL at startup (each workspace's proxy gets its own port). See [Proxy overview](proxy/overview.md) for details on proxy operation, CA certificate installation, and addons.
