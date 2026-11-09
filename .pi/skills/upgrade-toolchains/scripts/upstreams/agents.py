from __future__ import annotations

import re
import sys

sys.dont_write_bytecode = True

import upstreams.base
from upstreams.base import (
    ToolReleaseInfo,
    fetch_json,
    fetch_url,
    get_containerfile_args,
    sha256_of_url,
)


def resolve_pi() -> ToolReleaseInfo:
    """Resolve latest Pi coding agent release from npm."""
    data = fetch_json("https://registry.npmjs.org/@earendil-works/pi-coding-agent/latest")
    ver = data["version"]
    tarball_url = data["dist"]["tarball"]

    current_args = get_containerfile_args()
    curr_ver = current_args.get("PI_VERSION", "").strip('"').strip("'")
    curr_sha = current_args.get("PI_SHA256", "").strip('"').strip("'")

    if curr_ver == ver and curr_sha:
        sha = curr_sha
    elif upstreams.base.IS_UPGRADE_MODE:
        sha = sha256_of_url(tarball_url)
    else:
        sha = ""

    args = {"PI_VERSION": ver}
    if sha:
        args["PI_SHA256"] = sha

    return ToolReleaseInfo(
        tool="pi",
        version=ver,
        args=args,
        category="agents",
        release_url=f"https://www.npmjs.com/package/@earendil-works/pi-coding-agent/v/{ver}",
    )


def resolve_opencode() -> ToolReleaseInfo:
    """Resolve latest OpenCode agent release from npm."""
    data = fetch_json("https://registry.npmjs.org/@opencode/cli-linux-x64/latest")
    ver = data["version"]
    tarball_amd64 = data["dist"]["tarball"]
    tarball_arm64 = f"https://registry.npmjs.org/@opencode/cli-linux-arm64/-/cli-linux-arm64-{ver}.tgz"

    current_args = get_containerfile_args()
    curr_ver = current_args.get("OPENCODE_VERSION", "").strip('"').strip("'")
    curr_sha_amd64 = current_args.get("OPENCODE_SHA256_AMD64", "").strip('"').strip("'")
    curr_sha_arm64 = current_args.get("OPENCODE_SHA256_ARM64", "").strip('"').strip("'")

    if curr_ver == ver and curr_sha_amd64 and curr_sha_arm64:
        sha_amd64 = curr_sha_amd64
        sha_arm64 = curr_sha_arm64
    elif upstreams.base.IS_UPGRADE_MODE:
        sha_amd64 = sha256_of_url(tarball_amd64)
        sha_arm64 = sha256_of_url(tarball_arm64)
    else:
        sha_amd64 = ""
        sha_arm64 = ""

    args = {"OPENCODE_VERSION": ver}
    if sha_amd64:
        args["OPENCODE_SHA256_AMD64"] = sha_amd64
    if sha_arm64:
        args["OPENCODE_SHA256_ARM64"] = sha_arm64

    return ToolReleaseInfo(
        tool="opencode",
        version=ver,
        args=args,
        category="agents",
        release_url=f"https://www.npmjs.com/package/@opencode/cli-linux-x64/v/{ver}",
    )


def resolve_claude_code() -> ToolReleaseInfo:
    """Resolve latest Claude Code agent release from npm."""
    data = fetch_json("https://registry.npmjs.org/@anthropic-ai/claude-code-linux-x64/latest")
    ver = data["version"]
    tarball_amd64 = data["dist"]["tarball"]
    tarball_arm64 = (
        f"https://registry.npmjs.org/@anthropic-ai/claude-code-linux-arm64/-/claude-code-linux-arm64-{ver}.tgz"
    )

    current_args = get_containerfile_args()
    curr_ver = current_args.get("CLAUDE_CODE_VERSION", "").strip('"').strip("'")
    curr_sha_amd64 = current_args.get("CLAUDE_CODE_SHA256_AMD64", "").strip('"').strip("'")
    curr_sha_arm64 = current_args.get("CLAUDE_CODE_SHA256_ARM64", "").strip('"').strip("'")

    if curr_ver == ver and curr_sha_amd64 and curr_sha_arm64:
        sha_amd64 = curr_sha_amd64
        sha_arm64 = curr_sha_arm64
    elif upstreams.base.IS_UPGRADE_MODE:
        sha_amd64 = sha256_of_url(tarball_amd64)
        sha_arm64 = sha256_of_url(tarball_arm64)
    else:
        sha_amd64 = ""
        sha_arm64 = ""

    args = {"CLAUDE_CODE_VERSION": ver}
    if sha_amd64:
        args["CLAUDE_CODE_SHA256_AMD64"] = sha_amd64
    if sha_arm64:
        args["CLAUDE_CODE_SHA256_ARM64"] = sha_arm64

    return ToolReleaseInfo(
        tool="claude-code",
        version=ver,
        args=args,
        category="agents",
        release_url=f"https://www.npmjs.com/package/@anthropic-ai/claude-code-linux-x64/v/{ver}",
    )


def resolve_antigravity() -> ToolReleaseInfo:
    """Resolve latest Google Antigravity CLI release from Homebrew cask API."""
    data = fetch_json("https://formulae.brew.sh/api/cask/antigravity-cli.json")
    raw_version = data["version"]
    if "," in raw_version:
        ver, build_id = raw_version.split(",", 1)
    else:
        ver, build_id = raw_version, ""

    variations = data.get("variations", {})
    sha_amd64 = variations.get("x86_64_linux", {}).get("sha256", "")
    sha_arm64 = variations.get("arm64_linux", {}).get("sha256", "")

    return ToolReleaseInfo(
        tool="antigravity",
        version=ver,
        args={
            "ANTIGRAVITY_VERSION": ver,
            "ANTIGRAVITY_BUILD_ID": build_id,
            "ANTIGRAVITY_SHA256_AMD64": sha_amd64,
            "ANTIGRAVITY_SHA256_ARM64": sha_arm64,
        },
        category="agents",
        release_url="https://antigravity.google/product/antigravity-cli",
    )


def resolve_antigravity_acp() -> ToolReleaseInfo:
    """Resolve latest Antigravity ACP runtime release pinned by T3 Code."""
    url = "https://raw.githubusercontent.com/pingdotgg/t3code/main/apps/server/src/provider/antigravityRelease.ts"
    txt = fetch_url(url).decode("utf-8")
    m_ver = re.search(r'ANTIGRAVITY_RELEASE_VERSION\s*=\s*"([^"]+)"', txt)
    ver = m_ver.group(1) if m_ver else ""

    m_amd64 = re.search(r'"linux-x64".*?sha256:\s*"([a-f0-9]{64})"', txt, re.DOTALL)
    sha_amd64 = m_amd64.group(1) if m_amd64 else ""

    m_arm64 = re.search(r'"linux-arm64".*?sha256:\s*"([a-f0-9]{64})"', txt, re.DOTALL)
    sha_arm64 = m_arm64.group(1) if m_arm64 else ""

    return ToolReleaseInfo(
        tool="antigravity-acp",
        version=ver,
        args={
            "ANTIGRAVITY_ACP_VERSION": ver,
            "ANTIGRAVITY_ACP_SHA256_AMD64": sha_amd64,
            "ANTIGRAVITY_ACP_SHA256_ARM64": sha_arm64,
        },
        category="agents",
        release_url="https://github.com/pingdotgg/t3code",
    )
