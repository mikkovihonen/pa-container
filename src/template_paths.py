from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True

"""Chat template file path resolution and existence validation."""

from config import GLOBAL_CHAT_TEMPLATES_DIR, GLOBAL_CONFIG_DIR, REPO_ROOT


def resolve_chat_template_path(
    template_path: str,
    repo_root: Path | None = None,
    global_templates_dir: Path | None = None,
) -> Path:
    """Resolve a `--chat-template-file` flag path globally, expanding tilde and relative paths."""
    p = Path(template_path).expanduser()
    g_dir = global_templates_dir or GLOBAL_CHAT_TEMPLATES_DIR
    r_root = repo_root or REPO_ROOT

    if p.is_absolute():
        if p.exists():
            return p
        # If it points to global chat-templates directory but doesn't exist on disk,
        # check if it exists in the bundled repository chat-templates
        try:
            rel = p.relative_to(g_dir)
            bundled = r_root / "chat-templates" / rel
            if bundled.exists():
                return bundled.resolve()
        except ValueError:
            pass
        return p

    # 1. Directly under global chat-templates directory (~/.config/pi-container/chat-templates/)
    if (g_dir / p).exists():
        return (g_dir / p).resolve()

    # 2. Relative to ~/.config/pi-container/ (e.g. "chat-templates/<model>/...")
    if (GLOBAL_CONFIG_DIR / p).exists():
        return (GLOBAL_CONFIG_DIR / p).resolve()

    parts = p.parts

    # 3. If path starts with "chat-templates/", check under g_dir (without prefix)
    if len(parts) > 1 and parts[0] == "chat-templates":
        sub = Path(*parts[1:])
        if (g_dir / sub).exists():
            return (g_dir / sub).resolve()

    # 4. Check relative to repo_root or current working directory
    if (r_root / p).exists():
        return (r_root / p).resolve()
    if (r_root / "chat-templates" / p).exists():
        return (r_root / "chat-templates" / p).resolve()
    if (Path.cwd() / p).exists():
        return (Path.cwd() / p).resolve()

    # Fallback default: prefer global templates directory
    if len(parts) > 1 and parts[0] == "chat-templates":
        return (GLOBAL_CONFIG_DIR / p).resolve()
    return (g_dir / p).resolve()


def check_chat_template_paths(
    flags: list,
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

            resolved = resolve_chat_template_path(
                template_path,
                repo_root=repo_root,
                global_templates_dir=global_templates_dir,
            )
            if not resolved.exists():
                errors.append(f"flags[{i}]: --chat-template-file path does not exist: {resolved}")
    return errors
