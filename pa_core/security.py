from __future__ import annotations

"""Security policy definitions and preflight validations for pa-container."""

import ipaddress
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from logging_driver import LogCategory, get_category_logger
from network import load_project_config

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

# Well-known credential formats with distinctive prefixes. Used for the
# fail-closed scan of the final agent container environment: if any value
# matches a real-token shape, the run aborts before the container starts.
# Placeholders (e.g. GH_TOKEN_PLACEHOLDER) never match these patterns.
_REAL_TOKEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("GitHub classic PAT", re.compile(r"ghp_[A-Za-z0-9]{30,}")),
    ("GitHub OAuth token", re.compile(r"gho_[A-Za-z0-9]{30,}")),
    ("GitHub app token", re.compile(r"ghu_[A-Za-z0-9]{30,}")),
    ("GitHub refresh token", re.compile(r"ghr_[A-Za-z0-9]{30,}")),
    ("GitHub fine-grained PAT", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("GitLab PAT", re.compile(r"glpat-[A-Za-z0-9_\-]{20,}")),
    # Anthropic API keys ('sk-ant-api03-...'). The agent-native OAuth token
    # ('sk-ant-oat01-...') is an intentional real secret and must NOT match.
    ("Anthropic API key", re.compile(r"sk-ant-api\d*-[A-Za-z0-9_\-]{40,}")),
    ("OpenAI API key", re.compile(r"sk-proj-[A-Za-z0-9_\-]{40,}")),
    ("OpenAI legacy API key", re.compile(r"sk-[A-Za-z0-9]{40,}")),
)


def scan_env_for_real_tokens(
    env: dict[str, str],
    known_secrets: dict[str, str] | None = None,
) -> list[str]:
    """Scan final container env values for real credential material.

    Fail-closed check executed before the agent container starts. A value is
    a violation when it matches a well-known real-token format or equals a
    secret resolved host-side (trusted registry values such as gateway keys
    and source-control tokens).

    Args:
        env: The complete environment that will be passed to the agent container.
        known_secrets: Real secret values resolved host-side (name -> value).

    Returns:
        A list of human-readable violation descriptions (empty when clean).
    """
    violations: list[str] = []
    known_values: set[str] = {v for v in (known_secrets or {}).values() if v}
    for key, value in env.items():
        if not isinstance(value, str) or not value:
            continue
        if value in known_values:
            violations.append(f"{key} carries a real host-side secret value")
            continue
        for label, pattern in _REAL_TOKEN_PATTERNS:
            if pattern.search(value):
                violations.append(f"{key} matches a {label} format")
                break
    return violations


def read_security_config(config_dir: Path | None = None) -> SecurityConfig:
    """Read the ``security`` section from config.yaml."""
    cfg = load_project_config(config_dir)
    section = cfg.get("security")
    if not isinstance(section, dict):
        raise ValueError("Missing required 'security' configuration section in project config")

    for key in ("read_only_git_hooks", "blocked_mount_paths", "blocked_ip_ranges", "git_config_allowlist"):
        if key not in section:
            raise ValueError(f"Missing required 'security.{key}' configuration in project config")

    read_only_hooks = section["read_only_git_hooks"]
    if not isinstance(read_only_hooks, bool):
        raise ValueError(f"Invalid 'security.read_only_git_hooks': expected bool, got {type(read_only_hooks).__name__}")

    blocked_mounts = section["blocked_mount_paths"]
    if not isinstance(blocked_mounts, list):
        raise ValueError("Invalid 'security.blocked_mount_paths': expected list")

    blocked_ips = section["blocked_ip_ranges"]
    if not isinstance(blocked_ips, list):
        raise ValueError("Invalid 'security.blocked_ip_ranges': expected list")

    git_allowlist = section["git_config_allowlist"]
    if not isinstance(git_allowlist, list):
        raise ValueError("Invalid 'security.git_config_allowlist': expected list")

    return {
        "read_only_git_hooks": read_only_hooks,
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
        except Exception as e:
            logger.debug(f"Could not resolve blocked path '{pattern}': {e}")
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
                except Exception as e:
                    logger.debug(f"Error checking container path '{container_str}': {e}")

        # Check host source path safety
        try:
            host_path = Path(host_str).expanduser().resolve()
        except Exception as e:
            logger.debug(f"Could not resolve host path '{host_str}': {e}")
            continue

        for pattern, blocked in resolved_blocked:
            try:
                # Check if exact match or if host_path is a subdirectory/file inside blocked
                if host_path == blocked or host_path.is_relative_to(blocked):
                    errors.append(
                        f"Mount '{mount}' is blocked: host path '{host_str}' exposes sensitive path '{pattern}'."
                    )
                    break
            except Exception as e:
                logger.debug(f"Error evaluating relative path for '{host_path}' vs '{blocked}': {e}")
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
