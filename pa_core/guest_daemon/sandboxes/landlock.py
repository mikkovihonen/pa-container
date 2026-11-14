from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def build_landlock_command(
    command: list[str],
    rw_paths: list[str | Path],
    ro_paths: list[str | Path] | None = None,
    allow_tcp_connect: list[str] | None = None,
    helper_bin: Path = Path("/opt/pa/bin/pa-landlock-run"),
) -> list[str]:
    """Wrap command with Landlock runtime helper if available, or return command."""
    if not helper_bin.is_file():
        return list(command)

    args = [str(helper_bin)]
    for p in rw_paths:
        args.extend(["--rw-path", str(p)])
    if ro_paths:
        for p in ro_paths:
            args.extend(["--ro-path", str(p)])
    if allow_tcp_connect:
        for conn in allow_tcp_connect:
            args.extend(["--allow-tcp-connect", conn])

    args.extend(command)
    return args
