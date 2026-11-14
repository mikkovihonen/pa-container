from __future__ import annotations

import socket
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FactoryMetadata:
    name: str = "default-factory"
    description: str = ""


@dataclass
class ComputeSpec:
    backend: str = "auto"  # "auto" | "macos-tart" | "linux-incus" | "linux-cloud"
    cpus: int = 8
    memory_mb: int = 16384
    gpu: str = "optional"  # "none" | "optional" | "required"


@dataclass
class PackagesSpec:
    toolchains: list[str] = field(default_factory=list)
    acps: list[str] = field(default_factory=list)


@dataclass
class LlamaServerSpec:
    enabled: bool = False
    model: str = ""
    ctx_size: int = 32768
    gpu_layers: str = "all"


@dataclass
class InferenceSpec:
    llama_server: LlamaServerSpec = field(default_factory=LlamaServerSpec)


@dataclass
class UiSpec:
    t3_code: bool = False
    virtual_desktop: str = "none"  # "wayland" | "x11" | "macos-aqua" | "none"


@dataclass
class AgentSpec:
    id: str
    driver: str = "pi"
    uid: int = 2001
    proxy_port: int | None = None
    transparent_port: int | None = None
    branch_prefix: str = "pa"
    acps: list[str] = field(default_factory=list)
    allowlist: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)


@dataclass
class FactoryConfig:
    schema_version: str = "2.0"
    factory: FactoryMetadata = field(default_factory=FactoryMetadata)
    compute: ComputeSpec = field(default_factory=ComputeSpec)
    packages: PackagesSpec = field(default_factory=PackagesSpec)
    inference: InferenceSpec = field(default_factory=InferenceSpec)
    ui: UiSpec = field(default_factory=UiSpec)
    agents: list[AgentSpec] = field(default_factory=list)


def find_free_port() -> int:
    """Find and return an available ephemeral TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port: int = s.getsockname()[1]
        return port


def resolve_agent_ports(
    agents: list[AgentSpec],
    base_proxy_port: int = 8081,
    base_transparent_port: int = 8091,
    dynamic: bool = False,
) -> list[AgentSpec]:
    """Resolve and assign proxy_port and transparent_port for each agent.

    Honours explicit declarations. If unassigned and dynamic is True, allocates
    free ephemeral ports. If dynamic is False, derives ports from UID:
    proxy_port = 8080 + (uid - 2000), transparent_port = 8090 + (uid - 2000).
    """
    used_ports: set[int] = set()

    # Pre-collect explicitly specified ports
    for agent in agents:
        if agent.proxy_port is not None:
            used_ports.add(agent.proxy_port)
        if agent.transparent_port is not None:
            used_ports.add(agent.transparent_port)

    resolved: list[AgentSpec] = []
    for idx, agent in enumerate(agents):
        p_port = agent.proxy_port
        t_port = agent.transparent_port

        if p_port is None:
            if dynamic:
                while True:
                    candidate = find_free_port()
                    if candidate not in used_ports:
                        p_port = candidate
                        used_ports.add(candidate)
                        break
            else:
                offset = (agent.uid - 2000) if agent.uid >= 2000 else (idx + 1)
                candidate = 8080 + offset
                p_port = candidate
                used_ports.add(candidate)

        if t_port is None:
            if dynamic:
                while True:
                    candidate = find_free_port()
                    if candidate not in used_ports:
                        t_port = candidate
                        used_ports.add(candidate)
                        break
            else:
                offset = (agent.uid - 2000) if agent.uid >= 2000 else (idx + 1)
                candidate = 8090 + offset
                t_port = candidate
                used_ports.add(candidate)

        resolved.append(
            AgentSpec(
                id=agent.id,
                driver=agent.driver,
                uid=agent.uid,
                proxy_port=p_port,
                transparent_port=t_port,
                branch_prefix=agent.branch_prefix,
                acps=list(agent.acps),
                allowlist=list(agent.allowlist),
                tokens=list(agent.tokens),
            )
        )
    return resolved


def load_factory_config(path: Path | str | None = None) -> FactoryConfig:
    """Load a FactoryConfig from a factory.toml file.

    If path is None, looks for 'factory.toml' in current directory or project root.
    If no file is found, returns a default FactoryConfig with one agent.
    """
    target_path: Path | None = None
    if path is not None:
        target_path = Path(path)
    else:
        candidates = [Path.cwd() / "factory.toml", Path.cwd() / ".pa-container" / "factory.toml"]
        for c in candidates:
            if c.is_file():
                target_path = c
                break

    if target_path is None or not target_path.is_file():
        # Default single agent config
        return FactoryConfig(
            agents=[
                AgentSpec(
                    id="agent1",
                    driver="pi",
                    uid=2001,
                    proxy_port=8081,
                    transparent_port=8091,
                    branch_prefix="pa/agent1",
                )
            ]
        )

    with target_path.open("rb") as f:
        data = tomllib.load(f)

    meta_data = data.get("factory", {})
    factory_meta = FactoryMetadata(
        name=meta_data.get("name", "default-factory"),
        description=meta_data.get("description", ""),
    )

    comp_data = data.get("compute", {})
    compute = ComputeSpec(
        backend=comp_data.get("backend", "auto"),
        cpus=int(comp_data.get("cpus", 8)),
        memory_mb=int(comp_data.get("memory_mb", 16384)),
        gpu=comp_data.get("gpu", "optional"),
    )

    pkg_data = data.get("packages", {})
    packages = PackagesSpec(
        toolchains=pkg_data.get("toolchains", []),
        acps=pkg_data.get("acps", []),
    )

    inf_data = data.get("inference", {})
    llama_data = inf_data.get("llama_server", {})
    inference = InferenceSpec(
        llama_server=LlamaServerSpec(
            enabled=llama_data.get("enabled", False),
            model=llama_data.get("model", ""),
            ctx_size=int(llama_data.get("ctx_size", 32768)),
            gpu_layers=str(llama_data.get("gpu_layers", "all")),
        )
    )

    ui_data = data.get("ui", {})
    ui = UiSpec(
        t3_code=ui_data.get("t3_code", False),
        virtual_desktop=ui_data.get("virtual_desktop", "none"),
    )

    raw_agents = data.get("agents", [])
    agents: list[AgentSpec] = []
    for idx, a in enumerate(raw_agents):
        agent_id = a.get("id", f"agent{idx + 1}")
        uid = int(a.get("uid", 2001 + idx))
        proxy_port = a.get("proxy_port")
        transparent_port = a.get("transparent_port")
        agents.append(
            AgentSpec(
                id=agent_id,
                driver=a.get("driver", "pi"),
                uid=uid,
                proxy_port=int(proxy_port) if proxy_port is not None else None,
                transparent_port=int(transparent_port) if transparent_port is not None else None,
                branch_prefix=a.get("branch_prefix", f"pa/{agent_id}"),
                acps=a.get("acps", []),
                allowlist=a.get("allowlist", []),
                tokens=a.get("tokens", []),
            )
        )

    if not agents:
        agents.append(
            AgentSpec(
                id="agent1",
                driver="pi",
                uid=2001,
                proxy_port=8081,
                transparent_port=8091,
                branch_prefix="pa/agent1",
            )
        )

    return FactoryConfig(
        schema_version=data.get("schema_version", "2.0"),
        factory=factory_meta,
        compute=compute,
        packages=packages,
        inference=inference,
        ui=ui,
        agents=agents,
    )
