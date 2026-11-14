from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_VAULT_ROOT = Path("/var/pa-vault")

PRE_RECEIVE_HOOK = """#!/bin/sh
set -eu

AGENT_ID="${PA_AGENT_ID:-}"
if [ -z "$AGENT_ID" ]; then
    AGENT_ID="$(whoami)"
fi
ALLOWED_PREFIX="${PA_BRANCH_PREFIX:-pa/${AGENT_ID}/}"

while read -r oldrev newrev refname; do
    case "$refname" in
        refs/heads/*)
            branch="${refname#refs/heads/}"
            case "$branch" in
                pa/"$AGENT_ID"/*)
                    ;;
                *)
                    echo "PA-Git-Vault: Access Denied. Agent '$AGENT_ID' can only push to '$ALLOWED_PREFIX*', but attempted push to '$branch'." >&2
                    exit 1
                    ;;
            esac
            ;;
    esac
done
exit 0
"""


class GitVaultManager:
    """Manages the internal Git Vault, pre-receive ACLs, and instant CoW clones."""

    def __init__(self, vault_root: Path | None = None) -> None:
        self.vault_root = vault_root or DEFAULT_VAULT_ROOT

    def get_repo_path(self, project_name: str) -> Path:
        return self.vault_root / f"{project_name}.git"

    def get_reference_checkout(self, project_name: str) -> Path:
        return self.vault_root / "checkouts" / f"{project_name}-main"

    def init_bare_vault(self, project_name: str) -> Path:
        """Initialize bare Git repository in the vault with pre-receive ACL hooks."""
        repo_path = self.get_repo_path(project_name)
        repo_path.mkdir(parents=True, exist_ok=True)

        if not (repo_path / "HEAD").is_file():
            subprocess.run(["git", "init", "--bare", str(repo_path)], check=True, capture_output=True)

        # Install pre-receive hook for branch ACL
        hooks_dir = repo_path / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_file = hooks_dir / "pre-receive"
        hook_file.write_text(PRE_RECEIVE_HOOK)
        hook_file.chmod(0o755)

        return repo_path

    def update_reference_checkout(self, project_name: str, branch: str = "main") -> Path:
        """Update or create the clean reference checkout from bare vault."""
        repo_path = self.get_repo_path(project_name)
        checkout_path = self.get_reference_checkout(project_name)
        checkout_path.parent.mkdir(parents=True, exist_ok=True)

        if not (checkout_path / ".git").exists():
            subprocess.run(
                ["git", "clone", str(repo_path), str(checkout_path)],
                check=True,
                capture_output=True,
            )
        else:
            subprocess.run(
                ["git", "fetch", "origin"],
                cwd=checkout_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "checkout", branch],
                cwd=checkout_path,
                capture_output=True,
            )
            subprocess.run(
                ["git", "pull", "--ff-only", "origin", branch],
                cwd=checkout_path,
                capture_output=True,
            )

        return checkout_path

    def cow_clone_workspace(
        self,
        project_name: str,
        destination: Path,
        agent_id: str,
        branch_name: str | None = None,
        mock_cow: bool = False,
    ) -> Path:
        """Clone reference checkout to agent's workspace using filesystem Copy-on-Write."""
        ref_checkout = self.get_reference_checkout(project_name)
        if not ref_checkout.exists():
            # If reference checkout not populated yet, clone bare repo directly
            repo_path = self.get_repo_path(project_name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                shutil.rmtree(destination)
            subprocess.run(["git", "clone", str(repo_path), str(destination)], check=True, capture_output=True)
        else:
            if destination.exists():
                shutil.rmtree(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)

            if mock_cow:
                shutil.copytree(ref_checkout, destination)
            elif sys.platform == "darwin":
                # APFS CoW clone
                res = subprocess.run(["cp", "-c", "-R", str(ref_checkout), str(destination)], capture_output=True)
                if res.returncode != 0:
                    shutil.copytree(ref_checkout, destination)
            else:
                # Linux Btrfs/XFS CoW clone
                res = subprocess.run(
                    ["cp", "--reflink=always", "-a", str(ref_checkout), str(destination)], capture_output=True
                )
                if res.returncode != 0:
                    shutil.copytree(ref_checkout, destination)

        # Checkout dedicated agent branch
        target_branch = branch_name or f"pa/{agent_id}/task"
        if (destination / ".git").exists():
            subprocess.run(
                ["git", "checkout", "-B", target_branch],
                cwd=destination,
                check=True,
                capture_output=True,
            )

        return destination
