from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from backends.base import get_backend
from factory_schema import load_factory_config

log = logging.getLogger(__name__)


def review_agent_workspace(
    agent_id: str,
    host_repo: Path | None = None,
    open_ide: bool = False,
    ide_cmd: str | None = None,
    mock: bool = False,
) -> Path:
    """Fetch agent's branch from Factory VM Vault into host git worktree (.pa/review/<agent-id>).

    Args:
        agent_id: The ID of the agent to review (e.g. 'agent1' or 'lead-architect').
        host_repo: Root path of the host Git repository.
        open_ide: Whether to launch the developer's IDE on the review worktree.
        ide_cmd: Custom IDE launch command (e.g. 'code', 'cursor', 'zed').
        mock: If True, simulates worktree creation without executing git subprocesses.

    Returns:
        Path to the local review worktree.
    """
    repo = host_repo or Path.cwd()
    worktree_path = repo / ".pa" / "review" / agent_id

    if mock:
        worktree_path.mkdir(parents=True, exist_ok=True)
        return worktree_path

    config = load_factory_config(repo / "factory.toml")
    backend = get_backend(config)

    try:
        backend.fetch_agent_branch(agent_id=agent_id, host_repo=repo)
    except Exception as e:
        log.warning(f"Backend fetch_agent_branch failed, falling back to local worktree: {e}")
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        if not worktree_path.exists():
            subprocess.run(
                ["git", "worktree", "add", str(worktree_path), f"pa/{agent_id}/task"],
                cwd=repo,
                capture_output=True,
            )

    if open_ide:
        cmd = ide_cmd or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "code"
        if shutil.which(cmd):
            subprocess.Popen([cmd, str(worktree_path)])

    return worktree_path
