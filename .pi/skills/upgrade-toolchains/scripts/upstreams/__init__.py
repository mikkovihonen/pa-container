from __future__ import annotations

import sys
from typing import TYPE_CHECKING

sys.dont_write_bytecode = True

if TYPE_CHECKING:
    from collections.abc import Callable

    from upstreams.base import ToolReleaseInfo
from upstreams.agents import (
    resolve_antigravity,
    resolve_antigravity_acp,
    resolve_claude_code,
    resolve_opencode,
    resolve_pi,
)
from upstreams.github_git import (
    resolve_ast_grep,
    resolve_clangd,
    resolve_colgrep,
    resolve_fd,
    resolve_gopls,
    resolve_mold,
    resolve_podman,
    resolve_qdrant,
    resolve_ripgrep,
    resolve_rust_analyzer,
    resolve_sqlite_vec,
    resolve_tree_sitter_cli,
)
from upstreams.github_release import (
    resolve_aardvark_dns,
    resolve_chromium,
    resolve_gh,
    resolve_glab,
    resolve_netavark,
    resolve_t3,
    resolve_tea,
    resolve_zls,
)
from upstreams.language_manifests import (
    resolve_cafe,
    resolve_git,
    resolve_go,
    resolve_node,
    resolve_python,
    resolve_ruby,
    resolve_rust,
)
from upstreams.pypi import (
    resolve_az,
    resolve_podman_compose,
    resolve_python_dotenv,
    resolve_pyyaml,
    resolve_uv,
)

RESOLVERS: dict[str, Callable[[], ToolReleaseInfo]] = {
    # Core
    "python": resolve_python,
    "go": resolve_go,
    "rust": resolve_rust,
    "node": resolve_node,
    "podman": resolve_podman,
    "netavark": resolve_netavark,
    "aardvark-dns": resolve_aardvark_dns,
    "uv": resolve_uv,
    "podman-compose": resolve_podman_compose,
    "python-dotenv": resolve_python_dotenv,
    "pyyaml": resolve_pyyaml,
    # On-demand tools
    "chromium": resolve_chromium,
    "mold": resolve_mold,
    "git": resolve_git,
    "ripgrep": resolve_ripgrep,
    "fd": resolve_fd,
    "ast-grep": resolve_ast_grep,
    "tree-sitter-cli": resolve_tree_sitter_cli,
    "colgrep": resolve_colgrep,
    "qdrant": resolve_qdrant,
    "sqlite-vec": resolve_sqlite_vec,
    "rust-analyzer": resolve_rust_analyzer,
    "gopls": resolve_gopls,
    "clangd": resolve_clangd,
    "zls": resolve_zls,
    "ruby": resolve_ruby,
    "t3": resolve_t3,
    "gh": resolve_gh,
    "glab": resolve_glab,
    "tea": resolve_tea,
    "az": resolve_az,
    "cafe": resolve_cafe,
    # Agents
    "pi": resolve_pi,
    "opencode": resolve_opencode,
    "claude-code": resolve_claude_code,
    "antigravity": resolve_antigravity,
    "antigravity-acp": resolve_antigravity_acp,
}
