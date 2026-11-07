from __future__ import annotations

"""Security policy definitions and preflight validations for pa-container."""

import ipaddress
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from logging_driver import LogCategory, get_category_logger
from network import _egress_truthy, load_project_config

if TYPE_CHECKING:
    from config_types import SecurityConfig

logger = get_category_logger(__name__, LogCategory.SECURITY)

FORBIDDEN_CONTAINER_DESTINATION_PREFIXES: tuple[str, ...] = (
    "/workspace/.pa-container",
    "/workspace/.git/hooks",
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/root",
)

DEFAULT_SECURITY_CONFIG: SecurityConfig = {
    "read_only_git_hooks": True,
    "blocked_mount_paths": [
        "~/.ssh",
        "~/.gnupg",
        "~/.aws",
        "~/.azure",
        "~/.config/gcloud",
        "~/.kube",
        "~/.docker",
        "/var/run/docker.sock",
        "/var/run/podman/podman.sock",
        "/etc/shadow",
        "/etc/passwd",
        "/etc/sudoers",
        "/root",
    ],
    "blocked_ip_ranges": [
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    ],
    "git_config_allowlist": [
        "user.name",
        "user.email",
        "init.defaultBranch",
        "pull.rebase",
        "core.autocrlf",
        "core.filemode",
        "core.eol",
        "commit.gpgSign",
        "user.signingKey",
        "gpg.format",
        "gpg.ssh.program",
        "tag.gpgSign",
    ],
}


def read_security_config(config_dir: Path | None = None) -> SecurityConfig:
    """Read the ``security`` section from config.yaml with fail-safe defaults."""
    cfg = load_project_config(config_dir)
    section = cfg.get("security") or {}

    read_only_hooks = section.get("read_only_git_hooks")
    if read_only_hooks is None:
        read_only_hooks_val = DEFAULT_SECURITY_CONFIG["read_only_git_hooks"]
    else:
        read_only_hooks_val = _egress_truthy(read_only_hooks)

    blocked_mounts = section.get("blocked_mount_paths")
    if not isinstance(blocked_mounts, list):
        blocked_mounts = DEFAULT_SECURITY_CONFIG["blocked_mount_paths"]

    blocked_ips = section.get("blocked_ip_ranges")
    if not isinstance(blocked_ips, list):
        blocked_ips = DEFAULT_SECURITY_CONFIG["blocked_ip_ranges"]

    git_allowlist = section.get("git_config_allowlist")
    if not isinstance(git_allowlist, list):
        git_allowlist = DEFAULT_SECURITY_CONFIG["git_config_allowlist"]

    return {
        "read_only_git_hooks": read_only_hooks_val,
        "blocked_mount_paths": [str(p) for p in blocked_mounts],
        "blocked_ip_ranges": [str(ip) for ip in blocked_ips],
        "git_config_allowlist": [str(k) for k in git_allowlist],
    }


def validate_mount_paths(mounts: list[str], blocked_paths: list[str]) -> list[str]:
    """Validate that extra agent bind mounts do not expose dangerous host directories
    or override sensitive container destinations.

    Args:
        mounts: List of mount specifications (e.g. "host_path:container_path[:mode]").
        blocked_paths: List of forbidden host path patterns (e.g. "~/.ssh", "/var/run/docker.sock").

    Returns:
        List of error messages describing any forbidden mount violations.
    """
    errors: list[str] = []
    resolved_blocked: list[tuple[str, Path]] = []
    for pattern in blocked_paths:
        try:
            expanded = Path(pattern).expanduser().resolve()
            resolved_blocked.append((pattern, expanded))
        except Exception:
            continue

    forbidden_dest_paths = [PurePosixPath(p) for p in FORBIDDEN_CONTAINER_DESTINATION_PREFIXES]

    for mount in mounts:
        parts = mount.split(":")
        host_str = parts[0].strip() if parts else ""
        container_str = parts[1].strip() if len(parts) > 1 else ""

        if not host_str:
            continue

        # Check container destination path safety
        if container_str:
            if not container_str.startswith("/"):
                errors.append(
                    f"Mount '{mount}' is blocked: container path '{container_str}' must be an absolute path starting with '/'."
                )
            else:
                try:
                    norm_dest = PurePosixPath(container_str)
                    for forbidden in forbidden_dest_paths:
                        if norm_dest == forbidden or norm_dest.is_relative_to(forbidden):
                            errors.append(
                                f"Mount '{mount}' is blocked: container destination '{container_str}' "
                                f"attempts to override protected system or project path '{forbidden}'."
                            )
                            break
                except Exception:
                    pass

        # Check host source path safety
        try:
            host_path = Path(host_str).expanduser().resolve()
        except Exception:
            continue

        for pattern, blocked in resolved_blocked:
            try:
                # Check if exact match or if host_path is a subdirectory/file inside blocked
                if host_path == blocked or host_path.is_relative_to(blocked):
                    errors.append(
                        f"Mount '{mount}' is blocked: host path '{host_str}' exposes sensitive path '{pattern}'."
                    )
                    break
            except Exception:
                continue

    return errors


def is_ip_in_blocked_ranges(ip_str: str, blocked_ranges: list[str]) -> bool:
    """Check if an IP address string belongs to any of the blocked CIDR ranges.

    Args:
        ip_str: IPv4 or IPv6 address string.
        blocked_ranges: List of CIDR strings (e.g. "10.0.0.0/8", "169.254.0.0/16").

    Returns:
        True if the IP falls within any blocked network range.
    """
    try:
        ip = ipaddress.ip_address(ip_str.strip("[]"))
    except ValueError:
        return False

    for cidr in blocked_ranges:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            if ip in net:
                return True
        except ValueError:
            continue

    return False
