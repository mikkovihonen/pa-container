from __future__ import annotations

import sys
from typing import TypedDict

sys.dont_write_bytecode = True


class ProjectGitConfig(TypedDict, total=False):
    """Project-level git safety configuration."""

    safe_directory: bool
    rewrite_ssh_to_https: bool
