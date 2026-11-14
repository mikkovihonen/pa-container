from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def generate_seatbelt_profile(
    user: str,
    proxy_ip: str,
    proxy_port: int,
    dns_port: int = 5353,
    other_users: list[str] | None = None,
    vault_path: str = "/private/var/pa-vault",
) -> str:
    """Synthesize macOS Seatbelt (.sb) profile for sandboxing agent processes."""
    denied_reads = [f'    (subpath "/Users/{u}")' for u in (other_users or ["admin"])]
    denied_reads.append(f'    (subpath "{vault_path}")')
    denied_reads.append('    (subpath "/etc/pa/profiles")')
    denied_reads_clause = "\n".join(denied_reads)

    profile = f""";; PA-Container 2.0 Agent Seatbelt Profile: {user}
(version 1)
(allow default)

;; 1. Strict Network Lockdown
(deny network*)
(allow network-outbound (remote tcp "{proxy_ip}:{proxy_port}"))
(allow network-outbound (remote udp "{proxy_ip}:{dns_port}"))
(allow network-outbound (remote tcp "{proxy_ip}:{dns_port}"))
(allow network-outbound (remote unix-socket))
(allow network-inbound (local ip "localhost:*"))
(allow network-outbound (remote ip "localhost:*"))

;; 2. Cross-User & Vault Read Protection
(deny file-read*
{denied_reads_clause})

;; 3. Filesystem Write Jail
(deny file-write*)
(allow file-write*
    (subpath "/Users/{user}")
    (subpath "/private/tmp/pa-{user}")
    (subpath "/private/var/folders")
    (literal "/dev/null")
    (literal "/dev/zero")
    (literal "/dev/random")
    (literal "/dev/urandom")
    (literal "/dev/dtracehelper"))

;; 4. Allow Paravirtualized Metal GPU, CoreML, and IOKit Compute Access
(allow iokit-open
    (iokit-user-client-class "AGXDeviceUserClient")
    (iokit-user-client-class "AGXSharedUserClient")
    (iokit-user-client-class "IOSurfaceRootUserClient")
    (iokit-user-client-class "AppleKeyStoreUserClient"))
"""
    return profile


def build_sandbox_exec_command(profile_path: Path, command: list[str]) -> list[str]:
    """Wrap command with macOS sandbox-exec using the generated profile."""
    return ["sandbox-exec", "-f", str(profile_path)] + command
