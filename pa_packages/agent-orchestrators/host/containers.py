from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from logging_driver import LogCategory, get_category_logger
from project import project_key
from util import is_pid_alive

sys.dont_write_bytecode = True

logger = get_category_logger(__name__, LogCategory.PREFLIGHT)


@dataclass
class RunningT3ContainerInfo:
    """Details of a running T3 mode agent container for a workspace."""

    container_name: str
    container_id: str
    project_hash: str
    project_path: Path | None = None
    launcher_pid: int | None = None
    status: str = ""


def find_running_t3_container(
    project_dir: Path,
    runtime: str = "podman",
) -> RunningT3ContainerInfo | None:
    """Find any currently running T3 mode agent container for the specified project directory."""
    proj_hash = project_key(project_dir)
    try:
        proc = subprocess.run(
            [
                runtime,
                "ps",
                "--filter",
                f"label=pa-container.project.hash={proj_hash}",
                "--filter",
                "label=pa-container.type=agent",
                "--format",
                "json",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None

        try:
            raw = json.loads(proc.stdout)
            containers = raw if isinstance(raw, list) else [raw]
        except json.JSONDecodeError:
            containers = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    except Exception as e:
        logger.debug(f"Failed to query running containers for T3 check: {e}")
        return None

    for c in containers:
        if not isinstance(c, dict):
            continue

        raw_names = c.get("Names") or []
        if isinstance(raw_names, str):
            name = raw_names
        elif raw_names:
            name = raw_names[0]
        else:
            name = str(c.get("Id") or "")[:12]
        name = str(name).lstrip("/")

        labels = c.get("Labels") or {}
        launcher_pid_str = labels.get("pa-container.launcher_pid")
        launcher_pid: int | None = None
        if launcher_pid_str:
            try:
                launcher_pid = int(launcher_pid_str)
                if not is_pid_alive(launcher_pid):
                    continue
            except ValueError:
                pass

        # Determine if this container is running in T3 mode
        is_t3 = False
        if labels.get("pa-container.mode") == "t3" or any(
            "/home/agent/.t3" in str(m) or str(m).endswith("/.t3") for m in c.get("Mounts") or []
        ):
            is_t3 = True
        else:
            try:
                insp = subprocess.run(
                    [runtime, "inspect", name, "--format", "{{json .Config.Env}}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if insp.returncode == 0 and "PA_CONTAINER_MODE=t3" in insp.stdout:
                    is_t3 = True
            except Exception:
                pass

        if is_t3:
            path_str = labels.get("pa-container.project.path")
            proj_path = Path(path_str) if path_str else project_dir
            return RunningT3ContainerInfo(
                container_name=name,
                container_id=str(c.get("Id") or "")[:12],
                project_hash=proj_hash,
                project_path=proj_path,
                launcher_pid=launcher_pid,
                status=str(c.get("Status") or c.get("State") or "running"),
            )

    return None
