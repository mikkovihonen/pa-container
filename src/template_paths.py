from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True

"""Chat template file path resolution and existence validation."""

from config import GLOBAL_CHAT_TEMPLATES_DIR, REPO_ROOT


def resolve_chat_template_path(
    template_path: str,
    repo_root: Path | None = None,
    global_templates_dir: Path | None = None,
) -> Path:
    """Resolve a `--chat-template-file` flag path, expanding tildes and failing hard if absent."""
    p = Path(template_path).expanduser()
    if p.is_absolute():
        if p.is_file():
            return p.resolve()
        raise FileNotFoundError(f"Chat template file not found: {p}")

    g_dir = global_templates_dir or GLOBAL_CHAT_TEMPLATES_DIR
    candidate = (g_dir / p).resolve()
    if candidate.is_file():
        return candidate

    r_root = repo_root or REPO_ROOT
    bundled = (r_root / "coding-agent" / "default" / "global" / "chat-templates" / p).resolve()
    if bundled.is_file():
        return bundled

    raise FileNotFoundError(f"Chat template file not found at {candidate} or {bundled}")


def check_chat_template_paths(
    flags: list[str],
    repo_root: Path | None = None,
    global_templates_dir: Path | None = None,
) -> list[str]:
    """Validate that `--chat-template-file` paths specified in server flags exist on disk."""
    errors: list[str] = []
    for i, flag in enumerate(flags):
        if flag == "--chat-template-file":
            if i + 1 >= len(flags):
                errors.append(f"flags[{i}]: --chat-template-file has no following path")
                continue

            template_path = flags[i + 1]
            if not isinstance(template_path, str):
                errors.append(
                    f"flags[{i}]: --chat-template-file path is not a string (got {type(template_path).__name__})"
                )
                continue

            try:
                resolved = resolve_chat_template_path(
                    template_path,
                    repo_root=repo_root,
                    global_templates_dir=global_templates_dir,
                )
                if not resolved.exists():
                    errors.append(f"flags[{i}]: --chat-template-file path does not exist: {resolved}")
            except FileNotFoundError as e:
                errors.append(f"flags[{i}]: --chat-template-file path does not exist: {e}")
    return errors
