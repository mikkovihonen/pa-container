---
name: podman
description: Run, build, and orchestrate nested rootless containers inside the agent container using Podman and Docker Compose. Use whenever building container images, running testcontainers, starting multi-container dependencies (PostgreSQL, Redis), or inspecting container status.
---

# Podman & Nested Container Virtualization

## Overview

The container environment includes rootless Podman 6 and a `docker` compatibility wrapper. You can run OCI containers, build images, and launch `docker compose` services inside this container without root privileges.

- **Storage Driver**: `overlay` (backed by `/home/agent/.local/share/containers`)
- **Networking**: Bridge network with Netavark 2.0 and Aardvark-dns service discovery
- **Docker CLI**: Aliased to `/usr/local/bin/docker -> /usr/local/bin/podman`

## Common Workflows

### 1. Run a Container
Run an ephemeral container with port publishing:
```bash
podman run --rm -d -p 8080:8080 --name web nginx:alpine
```

### 2. Build a Containerfile
Build an image locally inside the container:
```bash
podman build -t my-app:latest .
```

### 3. Docker Compose Services
Start multi-container test environments:
```bash
podman compose up -d
```
All published ports on `0.0.0.0` or `127.0.0.1` are bound via rootlessport.

### 4. Container Management
Inspect running containers and logs:
```bash
podman ps -a
podman logs -f <container_id>
```
