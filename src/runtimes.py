from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config_types import DesktopConfig, DesktopGpuConfig, NestedContainersConfig, PortPublishConfig

sys.dont_write_bytecode = True

"""Podman container runtime layer.

Encapsulates Podman CLI flags and networking operations
(isolated netavark bridge network, proxy routing, IPv6 sysctl policy,
volume subpath mounts, nested containers) for orchestration.
"""

from logging_driver import LogCategory, get_category_logger

logger = get_category_logger(__name__, LogCategory.PREFLIGHT)


class PodmanRuntime:
    """Podman container runtime implementation with netavark networking and gvproxy DNS support."""

    name: str = "podman"
    default_upstream_network: str = "podman"
    proxy_isolated_interface: str = "eth1"
    ipv6_upstream_egress: bool = True

    #: Hostname podman maps to the host loopback (via gvproxy on macOS).
    HOST_INTERNAL_HOSTNAME: str = "host.containers.internal"
    #: gvproxy's fixed host address on a podman machine; used as a last resort
    #: when the hostname cannot be resolved via a probe container.
    HOST_INTERNAL_FALLBACK_IP: str = "192.168.127.254"

    def __init__(self, upstream_network: str | None = None) -> None:
        self.upstream_network: str = upstream_network or self.default_upstream_network

    # ── Isolated network lifecycle ───────────────────────────────────────
    def create_isolated_network_argv(self, network_name: str, ipv6: bool = False) -> list[str]:
        """Argv (after the CLI binary) that creates the internal isolated network."""
        argv = ["network", "create", "--internal", "--disable-dns"]
        if ipv6:
            argv += ["--ipv6"]
        argv.append(network_name)
        return argv

    def delete_isolated_network_argv(self, network_name: str) -> list[str]:
        """Argv that removes the isolated network on shutdown."""
        return ["network", "rm", network_name]

    # ── Upstream IPv6 capability ─────────────────────────────────────────
    def upstream_network_has_ipv6(self) -> bool | None:
        """Whether the upstream network is configured for IPv6 (best-effort)."""
        try:
            result = subprocess.run(
                [self.name, "network", "inspect", self.upstream_network],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout)
        except Exception as e:
            logger.warning(f"Could not inspect upstream network {self.upstream_network}: {e}")
            return None

        entry = data[0] if isinstance(data, list) and data else data
        if not isinstance(entry, dict):
            return None
        return self._network_entry_has_ipv6(entry)

    def _network_entry_has_ipv6(self, entry: dict[str, object]) -> bool | None:
        """Parse a ``network inspect`` entry for IPv6 enablement."""
        if entry.get("ipv6_enabled") is True:
            return True
        subnets = entry.get("subnets")
        if isinstance(subnets, list):
            for sub in subnets:
                if isinstance(sub, dict) and ":" in str(sub.get("subnet", "")):
                    return True
        return False

    # ── Proxy container networking ───────────────────────────────────────
    def proxy_network_args(self, isolated_network: str) -> list[str]:
        """``run`` flags attaching the proxy to upstream (eth0) + isolated (eth1)."""
        return [
            "--network",
            f"{self.upstream_network}:interface_name=eth0",
            "--network",
            f"{isolated_network}:interface_name=eth1",
        ]

    def proxy_extra_run_args(self) -> list[str]:
        """Extra runtime-specific ``run`` flags for the proxy container."""
        return ["--sysctl", "net.ipv4.ip_forward=1"]

    def ipv6_run_args(self, enabled: bool, forwarding: bool = False) -> list[str]:
        """``run`` flags that enforce the IPv6 policy for a container."""
        if not enabled:
            return ["--sysctl", "net.ipv6.conf.all.disable_ipv6=1"]
        if forwarding:
            return ["--sysctl", "net.ipv6.conf.all.forwarding=1"]
        return []

    # ── Agent container networking ───────────────────────────────────────
    def agent_network_args(self, isolated_network: str, proxy_isolated_ip: str) -> list[str]:
        """``run`` flags for the agent: isolated network only, routed via the proxy."""
        return [
            "--network",
            isolated_network,
            "--dns",
            proxy_isolated_ip,
            "--cap-add",
            "NET_ADMIN",
            "--env",
            f"DEFAULT_ROUTE={proxy_isolated_ip}",
        ]

    # ── Mounts ───────────────────────────────────────────────────────────
    def tmpfs_args(self, destination: str) -> list[str]:
        """Flags mounting a writable tmpfs at ``destination`` with nodev,nosuid."""
        return ["--mount", f"type=tmpfs,tmpfs-mode=1777,notmpcopyup,nodev,nosuid,destination={destination}"]

    def volume_subpath_args(
        self,
        volume_name: str,
        destination: str,
        subpath: str,
        read_only: bool = False,
    ) -> list[str]:
        """Flags mounting a subpath of a named volume at ``destination`` with nodev,nosuid."""
        mode = ",ro" if read_only else ""
        return [
            "--mount",
            f"type=volume,src={volume_name},dst={destination},subpath={subpath},nodev,nosuid{mode}",
        ]

    # ── Nested containers (config.yaml nested_containers) ────────────────
    def nested_container_args(self, cfg: NestedContainersConfig, project_hash: str) -> list[str]:
        """Return ``run`` flags enabling rootless podman inside the agent container."""
        if not cfg.get("enabled"):
            return []
        store = "/home/agent/.local/share/containers"
        storage_args = (
            self.tmpfs_args(store)
            if cfg.get("storage") == "tmpfs"
            else ["--volume", f"{self.nested_volume_name(project_hash)}:{store}"]
        )
        return [
            "--device",
            "/dev/fuse",
            "--device",
            "/dev/net/tun",
            "--security-opt",
            self._nested_security_opt(str(cfg.get("security") or "disable")),
            "--security-opt",
            "unmask=ALL",
            "--cap-add",
            "SYS_ADMIN",
            *storage_args,
            "--env",
            "XDG_RUNTIME_DIR=/run/user/1000",
            "--env",
            "PI_CONTAINER_NESTED=true",
        ]

    def port_publish_args(self, ports: PortPublishConfig) -> list[str]:
        """Return ``-p`` flags publishing container ports to the host."""
        host_bind = "127.0.0.1:" if ports.get("expose", "localhost") != "lan" else ""
        return [flag for host, agent in ports.get("publish") or [] for flag in ("-p", f"{host_bind}{host}:{agent}")]

    def nested_port_args(self, cfg: NestedContainersConfig) -> list[str]:
        """Return ``-p`` flags publishing nested-container service ports to the host."""
        if not cfg.get("enabled"):
            return []
        return self.port_publish_args(cfg.get("ports") or {"expose": "localhost", "publish": []})

    # ── Virtual desktop & GPU passthrough ───────────────────────────────
    def opportunistic_gpu_args(self, gpu_cfg: DesktopGpuConfig | None = None) -> list[str]:
        """Return DRI device flags if GPU is enabled and /dev/dri exists on host."""
        from pathlib import Path

        mode = (gpu_cfg or {}).get("enabled", "auto")
        if mode is False or str(mode).lower() in ("false", "0", "off", "no"):
            return []

        if Path("/dev/dri").exists():
            return ["--device", "/dev/dri", "--group-add", "keep-groups"]
        elif mode is True or str(mode).lower() in ("true", "1", "yes", "on"):
            logger.warning(
                "/dev/dri requested by config but does not exist on host; falling back to software rasterizer."
            )
        return []

    def desktop_run_args(self, cfg: DesktopConfig, novnc_port: int, vnc_port: int) -> list[str]:
        """Return runtime flags publishing desktop ports and setting Wayland/X11 environment."""
        if not cfg.get("enabled"):
            return []
        novnc_cfg = cfg.get("novnc") or {}
        vnc_cfg = cfg.get("vnc") or {}
        novnc_bind = "" if novnc_cfg.get("expose") == "lan" else "127.0.0.1:"
        vnc_bind = "" if vnc_cfg.get("expose") == "lan" else "127.0.0.1:"
        resolution = cfg.get("resolution", "1920x1080")
        return [
            "-p",
            f"{novnc_bind}{novnc_port}:6080",
            "-p",
            f"{vnc_bind}{vnc_port}:5900",
            "--env",
            "PI_CONTAINER_DESKTOP=true",
            "--env",
            "DISPLAY=:0",
            "--env",
            "WAYLAND_DISPLAY=wayland-0",
            "--env",
            "XDG_RUNTIME_DIR=/run/user/1000",
            "--env",
            f"PI_DESKTOP_RESOLUTION={resolution}",
        ]

    @staticmethod
    def nested_volume_name(project_hash: str) -> str:
        """Return the deterministic volume name for a project's nested image store."""
        return f"pi-nested-{project_hash}"

    @staticmethod
    def _nested_security_opt(security: str) -> str:
        """Translate the nesting security configuration into runtime SELinux flags."""
        return "label=type:container_engine_t" if security == "engine_t" else "label=disable"

    # ── Host llama-server reachability ──────────────────────────────────
    def llama_host_addr(self) -> str:
        return self.HOST_INTERNAL_HOSTNAME

    def resolve_llama_host_addr(self, probe_image: str | None = None) -> str:
        """Resolve the host machine address (``host.containers.internal``) to a numeric IP."""
        if probe_image:
            try:
                result = subprocess.run(
                    [
                        self.name,
                        "run",
                        "--rm",
                        "--network",
                        self.upstream_network,
                        "--entrypoint",
                        "getent",
                        probe_image,
                        "hosts",
                        self.HOST_INTERNAL_HOSTNAME,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                tokens = result.stdout.split()
                if tokens:
                    logger.info(f"Resolved {self.HOST_INTERNAL_HOSTNAME} → {tokens[0]}")
                    return tokens[0]
            except Exception as e:
                logger.warning(f"Could not probe {self.HOST_INTERNAL_HOSTNAME}: {e}")

        logger.info(f"Falling back to {self.HOST_INTERNAL_FALLBACK_IP} for llama host address")
        return self.HOST_INTERNAL_FALLBACK_IP
