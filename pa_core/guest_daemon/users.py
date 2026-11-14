from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def get_default_home_base() -> Path:
    if sys.platform == "darwin":
        return Path("/Users")
    return Path("/home")


def ensure_agent_user(
    username: str,
    uid: int,
    home_base: Path | None = None,
    mock: bool = False,
) -> Path:
    """Ensure an unprivileged POSIX user exists with directory permissions 0700.

    Args:
        username: POSIX user name (e.g. 'agent1').
        uid: User ID (UID >= 2001).
        home_base: Parent path for home directories (/home on Linux, /Users on macOS).
        mock: If True, skips actual OS useradd/dscl syscalls (for test environments).

    Returns:
        Path to the user's home directory.
    """
    base = home_base or get_default_home_base()
    home_dir = base / username

    if not mock:
        if sys.platform == "darwin":
            # macOS user provisioning via dscl / sysadminctl
            try:
                # Check if user already exists
                res = subprocess.run(["id", username], capture_output=True, text=True)
                if res.returncode != 0:
                    subprocess.run(
                        [
                            "sysadminctl",
                            "-addUser",
                            username,
                            "-UID",
                            str(uid),
                            "-home",
                            str(home_dir),
                            "-shell",
                            "/bin/bash",
                        ],
                        check=True,
                        capture_output=True,
                    )
            except Exception as e:
                log.warning(f"Could not provision macOS user {username} via sysadminctl: {e}")
        else:
            # Linux user provisioning via useradd
            try:
                res = subprocess.run(["id", username], capture_output=True, text=True)
                if res.returncode != 0:
                    subprocess.run(
                        ["useradd", "-u", str(uid), "-d", str(home_dir), "-m", "-s", "/bin/bash", username],
                        check=True,
                        capture_output=True,
                    )
            except Exception as e:
                log.warning(f"Could not provision Linux user {username} via useradd: {e}")

    # Ensure home directory and standard subdirectories exist with 0700 permissions
    try:
        home_dir.mkdir(parents=True, exist_ok=True)
        (home_dir / "workspace").mkdir(parents=True, exist_ok=True)
        (home_dir / ".cache").mkdir(parents=True, exist_ok=True)
        (home_dir / ".config").mkdir(parents=True, exist_ok=True)
        os.chmod(home_dir, 0o700)
    except Exception as e:
        log.warning(f"Failed to set 0700 permissions on {home_dir}: {e}")

    return home_dir
