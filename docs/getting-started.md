# Getting Started

## Prerequisites

Install the following tools on your host machine before running:

- **[uv](https://docs.astral.sh/uv/)**: Manages the Python environment and dependencies for the host-side build and run CLI.
    - On macOS: `brew install uv`
    - Other platforms: `curl -LsSf https://astral.sh/uv/install.sh | sh`
    - `pa` invokes `uv run`. The `uv run` command creates `.venv` and installs the declared dependencies (including the `hf` CLI and `huggingface_hub`) automatically on first use. You do not need a manual `pip install`.

- **[podman](https://podman.io)**: the only supported container runtime.
    - On macOS: `brew install podman`, then **`podman machine init --memory 4096`** and `podman machine start`
    - On Linux (Debian/Ubuntu): `sudo apt install podman`, or your distro's package manager

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
    - On Linux (Debian/Ubuntu): `sudo apt install llama.cpp`
    - On Linux (other): [build from source](https://github.com/ggml-org/llama.cpp)
    - On WSL2: `sudo apt install llama.cpp`

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
- **podman on macOS**: containers run inside a Linux VM (no `podman0` bridge exists on the host). The system does not use `socat`. The proxy reaches host `llama-server` via `host.containers.internal` (gvproxy). The isolated network is created `--internal --disable-dns`. The proxy's interfaces are pinned (`interface_name=eth0` / `interface_name=eth1`) so the isolated network is deterministically `eth1`. See [`src/runtimes.py`](https://github.com/mikkovihonen/pa-container/blob/main/src/runtimes.py).
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

This builds three images, in this order:

1. `pa-container-agent-builder:local` — the [toolchain image](design-details.md#toolchain-builder-image). Compiles CPython 3.14 (PGO), podman and netavark/aardvark-dns from source, and stages Node from the official nodejs.org tarball. **A few minutes** on a 9-core/8 GB machine.

    `NODE_SOURCE=build pa build` compiles Node from source instead, which takes **about an hour** (measured: ~65 min at 3 compile jobs). It buys a trixie-native build rather than the generic-glibc official one. Node has no build tags worth choosing, so unlike podman there is no correctness argument for it. The default `prebuilt` mode stages byte-for-byte the same Node the old `node:` base image shipped, since that image is this same tarball extracted into `/usr/local`.

    Compile parallelism is capped by available memory rather than core count, so a bigger machine directly shortens this step (`MAKE_JOBS=<n>` overrides the cap). Later builds skip the image entirely unless one of its pinned versions changes, and each component is a separate stage, so bumping podman does not rebuild Node.

    Every version, git commit and SHA-256 it builds from is an `ARG` in [`coding-agent-builder/Containerfile`](https://github.com/mikkovihonen/pa-container/blob/main/coding-agent-builder/Containerfile). That one file is where you bump a component.
2. `pa-container-agent-proxy:local` — the transparent proxy, which copies its CPython and `uv` out of the builder image so that it runs [the same Python as the agent](design-details.md#uniform-python-across-both-images).
3. `pa-container-agent:local` — the main agent, which copies the mitmproxy CA certificate out of the proxy image and its whole toolchain out of the builder image.

The order is not optional: the proxy image `COPY --from`s the builder, and the agent image `COPY --from`s both of the others.

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
