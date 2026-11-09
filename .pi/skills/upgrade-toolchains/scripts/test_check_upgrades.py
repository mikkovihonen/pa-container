from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.dont_write_bytecode = True

# Add scripts directory to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_upgrades import (
    check_tool,
    format_table,
    get_current_tool_version,
    read_containerfile_args,
    run_verify,
    update_containerfile_arg,
    upgrade_tool,
)
from upstreams.base import ToolReleaseInfo, parse_version_tuple


class TestVersionParsing(unittest.TestCase):
    def test_parse_version_tuple_standard(self) -> None:
        self.assertEqual(parse_version_tuple("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version_tuple("1.20.5"), (1, 20, 5))
        self.assertEqual(parse_version_tuple("0.4.5-alpha.1"), (0, 4, 5, 1))

    def test_parse_version_tuple_dates(self) -> None:
        self.assertEqual(parse_version_tuple("2026-03-01"), (2026, 3, 1))
        self.assertEqual(parse_version_tuple("2026.04.12"), (2026, 4, 12))

    def test_parse_version_tuple_sorting(self) -> None:
        versions = ["v1.2.0", "v1.10.0", "v1.9.5", "v2.0.0"]
        sorted_vers = sorted(versions, key=parse_version_tuple)
        self.assertEqual(sorted_vers, ["v1.2.0", "v1.9.5", "v1.10.0", "v2.0.0"])


class TestContainerfileParsing(unittest.TestCase):
    def test_read_containerfile_args(self) -> None:
        from tempfile import NamedTemporaryFile

        sample = """
# Header comment
ARG MOLD_VERSION=2.40.1
ARG MOLD_COMMIT=abc1234
ARG EMPTY_VAL=
ARG QUOTED_VAL="test-1.0"
"""
        with NamedTemporaryFile("w+", delete=False) as tf:
            tf.write(sample)
            tf.flush()
            p = Path(tf.name)

        try:
            args = read_containerfile_args(p)
            self.assertEqual(args["MOLD_VERSION"], "2.40.1")
            self.assertEqual(args["MOLD_COMMIT"], "abc1234")
            self.assertEqual(args["EMPTY_VAL"], "")
            self.assertEqual(args["QUOTED_VAL"], '"test-1.0"')
        finally:
            p.unlink(missing_ok=True)

    def test_get_current_tool_version(self) -> None:
        args = {
            "MOLD_VERSION": "2.40.1",
            "TREE_SITTER_VERSION": '"v0.25.3"',
            "AARDVARK_VERSION": "v1.14.0",
            "COLGREP_VERSION": "v0.1.0",
            "SQLITE_VEC_VERSION": "v0.1.6",
            "PYTHON_VERSION": "3.15.2",
            "PI_VERSION": "1.5.0",
            "OPENCODE_VERSION": "2.2.5",
            "CLAUDE_CODE_VERSION": "2.1.319",
            "ANTIGRAVITY_VERSION": "1.5.2",
            "ANTIGRAVITY_ACP_VERSION": "1.4.5",
            "CHROMIUM_VERSION": "157.0.8103.38",
        }
        self.assertEqual(get_current_tool_version("mold", args), "2.40.1")
        self.assertEqual(get_current_tool_version("tree-sitter-cli", args), "v0.25.3")
        self.assertEqual(get_current_tool_version("aardvark-dns", args), "v1.14.0")
        self.assertEqual(get_current_tool_version("colgrep", args), "v0.1.0")
        self.assertEqual(get_current_tool_version("sqlite-vec", args), "v0.1.6")
        self.assertEqual(get_current_tool_version("python", args), "3.15.2")
        self.assertEqual(get_current_tool_version("pi", args), "1.5.0")
        self.assertEqual(get_current_tool_version("opencode", args), "2.2.5")
        self.assertEqual(get_current_tool_version("claude-code", args), "2.1.319")
        self.assertEqual(get_current_tool_version("antigravity", args), "1.5.2")
        self.assertEqual(get_current_tool_version("antigravity-acp", args), "1.4.5")
        self.assertEqual(get_current_tool_version("chromium", args), "157.0.8103.38")
        self.assertEqual(get_current_tool_version("nonexistent", args), "")

    def test_update_containerfile_arg_single_line(self) -> None:
        content = "FROM alpine:3.20\nARG MOLD_VERSION=2.40.1\nARG MOLD_COMMIT=oldhash\nRUN echo building...\n"
        updated = update_containerfile_arg(content, "MOLD_VERSION", "2.41.0")
        self.assertIn("ARG MOLD_VERSION=2.41.0\n", updated)
        self.assertIn("ARG MOLD_COMMIT=oldhash\n", updated)

        updated2 = update_containerfile_arg(updated, "MOLD_COMMIT", "newhash")
        self.assertIn("ARG MOLD_COMMIT=newhash\n", updated2)

    def test_update_containerfile_arg_multiline(self) -> None:
        content = 'ARG UV_WHEEL_HASHES="\\\n  --hash=sha256:111\\\n  --hash=sha256:222"\nRUN uv --version\n'
        new_val = '"\\\n  --hash=sha256:333\\\n  --hash=sha256:444"'
        updated = update_containerfile_arg(content, "UV_WHEEL_HASHES", new_val)
        self.assertIn('ARG UV_WHEEL_HASHES="\\\n  --hash=sha256:333\\\n  --hash=sha256:444"', updated)
        self.assertIn("RUN uv --version\n", updated)


class TestCheckTool(unittest.TestCase):
    def test_check_tool_up_to_date(self) -> None:
        fake_info = ToolReleaseInfo(
            tool="test-tool",
            version="1.0.0",
            args={"TEST_TOOL_VERSION": "1.0.0", "TEST_TOOL_COMMIT": "abc"},
            category="compilers",
        )
        with patch.dict("check_upgrades.RESOLVERS", {"test-tool": lambda: fake_info}):
            current_args = {"TEST_TOOL_VERSION": "1.0.0", "TEST_TOOL_COMMIT": "abc"}
            res = check_tool("test-tool", current_args)
            self.assertTrue(res["up_to_date"])
            self.assertEqual(res["current"], "1.0.0")
            self.assertEqual(res["latest"], "1.0.0")

    def test_check_tool_outdated(self) -> None:
        fake_info = ToolReleaseInfo(
            tool="test-tool",
            version="1.1.0",
            args={"TEST_TOOL_VERSION": "1.1.0", "TEST_TOOL_COMMIT": "def"},
            category="compilers",
        )
        with patch.dict("check_upgrades.RESOLVERS", {"test-tool": lambda: fake_info}):
            current_args = {"TEST_TOOL_VERSION": "1.0.0", "TEST_TOOL_COMMIT": "abc"}
            res = check_tool("test-tool", current_args)
            self.assertFalse(res["up_to_date"])
            self.assertEqual(res["current"], "1.0.0")
            self.assertEqual(res["latest"], "1.1.0")

    def test_check_tool_same_version_different_commit(self) -> None:
        fake_info = ToolReleaseInfo(
            tool="test-tool",
            version="1.0.0",
            args={"TEST_TOOL_VERSION": "1.0.0", "TEST_TOOL_COMMIT": "newhash"},
            category="compilers",
        )
        with patch.dict("check_upgrades.RESOLVERS", {"test-tool": lambda: fake_info}):
            current_args = {"TEST_TOOL_VERSION": "1.0.0", "TEST_TOOL_COMMIT": "oldhash"}
            res = check_tool("test-tool", current_args)
            self.assertFalse(res["up_to_date"])

    def test_check_tool_resolver_error(self) -> None:
        def failing_resolver() -> ToolReleaseInfo:
            raise RuntimeError("Network timeout")

        with patch.dict("check_upgrades.RESOLVERS", {"test-tool": failing_resolver}):
            current_args = {"TEST_TOOL_VERSION": "1.0.0"}
            res = check_tool("test-tool", current_args)
            self.assertIn("Network timeout", res["error"])
            self.assertEqual(res["latest"], "error")

    def test_check_tool_unregistered(self) -> None:
        res = check_tool("unknown-tool", {})
        self.assertEqual(res["error"], "No resolver registered")


class TestFormatTable(unittest.TestCase):
    def test_format_table(self) -> None:
        results = [
            {
                "tool": "mold",
                "category": "compilers",
                "current": "v2.40.1",
                "latest": "v2.40.2",
                "up_to_date": False,
            },
            {
                "tool": "git",
                "category": "vcs",
                "current": "v2.49.0",
                "latest": "v2.49.0",
                "up_to_date": True,
            },
            {
                "tool": "broken",
                "category": "error",
                "current": "1.0",
                "latest": "error",
                "up_to_date": True,
                "error": "Failed",
            },
        ]
        table = format_table(results)
        self.assertIn("mold", table)
        self.assertIn("compilers", table)
        self.assertIn("⚑ Upgrade available", table)
        self.assertIn("✓ Up to date", table)
        self.assertIn("✗ Error: Failed", table)


class TestUpgradeTool(unittest.TestCase):
    def test_upgrade_tool_applies_args(self, tmp_path: Path | None = None) -> None:
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile("w+", delete=False) as tf:
            tf.write("ARG MOLD_VERSION=2.40.1\nARG MOLD_COMMIT=old\n")
            tf.flush()
            tmp_path = Path(tf.name)

        try:
            info = ToolReleaseInfo(
                tool="mold",
                version="2.40.2",
                args={"MOLD_VERSION": "2.40.2", "MOLD_COMMIT": "new"},
                category="compilers",
            )
            upgrade_tool("mold", info, tmp_path)
            content = tmp_path.read_text()
            self.assertIn("ARG MOLD_VERSION=2.40.2\n", content)
            self.assertIn("ARG MOLD_COMMIT=new\n", content)
        finally:
            tmp_path.unlink(missing_ok=True)


class TestVerify(unittest.TestCase):
    @patch("subprocess.run")
    def test_run_verify_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(run_verify())
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_run_verify_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1)
        self.assertFalse(run_verify())


class TestGroupsAndResolvers(unittest.TestCase):
    def test_every_group_tool_has_a_resolver(self) -> None:
        from check_upgrades import GROUPS
        from upstreams import RESOLVERS

        for group, tools in GROUPS.items():
            for tool in tools:
                self.assertIn(
                    tool,
                    RESOLVERS,
                    f"Tool '{tool}' in group '{group}' has no resolver in RESOLVERS",
                )

    def test_every_containerfile_version_arg_is_monitored(self) -> None:
        from check_upgrades import CONTAINERFILE, read_containerfile_args
        from upstreams import RESOLVERS

        args = read_containerfile_args(CONTAINERFILE)
        version_args = [k for k in args if k.endswith("_VERSION")]

        # Companion tools resolved jointly with their parent tool or internal capabilities:
        # ZIG_VERSION -> resolved by zls
        # AZURE_DEVOPS_VERSION -> resolved by az
        # BUN_VERSION -> resolved by cafe
        # VIRTUAL_DESKTOP_VERSION -> internal platform package
        companion_args = {"ZIG_VERSION", "AZURE_DEVOPS_VERSION", "BUN_VERSION", "VIRTUAL_DESKTOP_VERSION"}

        # Tools with non-standard version ARG naming:
        special_names = {
            "tree-sitter-cli": "TREE_SITTER_VERSION",
            "aardvark-dns": "AARDVARK_VERSION",
        }

        covered_args: set[str] = set(companion_args)
        for tool in RESOLVERS:
            if tool in special_names:
                covered_args.add(special_names[tool])
            else:
                covered_args.add(f"{tool.replace('-', '_').upper()}_VERSION")

        uncovered = [v for v in version_args if v not in covered_args]
        self.assertEqual(
            uncovered,
            [],
            f"Containerfile has unmonitored version ARGs: {uncovered}",
        )


class TestAgentResolvers(unittest.TestCase):
    @patch("upstreams.agents.fetch_json")
    @patch("upstreams.agents.get_containerfile_args")
    def test_resolve_pi(self, mock_args: MagicMock, mock_fetch: MagicMock) -> None:
        from upstreams.agents import resolve_pi

        mock_fetch.return_value = {
            "version": "1.5.0",
            "dist": {"tarball": "https://registry.npmjs.org/@earendil-works/pi-coding-agent/-/pi-coding-agent-1.5.0.tgz"},
        }
        mock_args.return_value = {"PI_VERSION": "1.5.0", "PI_SHA256": "abc123"}
        info = resolve_pi()
        self.assertEqual(info.tool, "pi")
        self.assertEqual(info.version, "1.5.0")
        self.assertEqual(info.args["PI_SHA256"], "abc123")

    @patch("upstreams.agents.fetch_json")
    def test_resolve_antigravity(self, mock_fetch: MagicMock) -> None:
        from upstreams.agents import resolve_antigravity

        mock_fetch.return_value = {
            "version": "1.5.3,6604829099950080",
            "variations": {
                "x86_64_linux": {"sha256": "sha-amd64"},
                "arm64_linux": {"sha256": "sha-arm64"},
            },
        }
        info = resolve_antigravity()
        self.assertEqual(info.tool, "antigravity")
        self.assertEqual(info.version, "1.5.3")
        self.assertEqual(info.args["ANTIGRAVITY_BUILD_ID"], "6604829099950080")
        self.assertEqual(info.args["ANTIGRAVITY_SHA256_AMD64"], "sha-amd64")
        self.assertEqual(info.args["ANTIGRAVITY_SHA256_ARM64"], "sha-arm64")

    @patch("upstreams.agents.fetch_url")
    def test_resolve_antigravity_acp(self, mock_fetch: MagicMock) -> None:
        from upstreams.agents import resolve_antigravity_acp

        mock_ts = """
        const ANTIGRAVITY_RELEASE_VERSION = "1.4.5";
        ["linux-x64", {
          version: ANTIGRAVITY_RELEASE_VERSION,
          sha256: "923923a0d7dc8073f66cc6f78647a3107e3a7ee2b7e1a24df8b3927b5188013b",
        }],
        ["linux-arm64", {
          version: ANTIGRAVITY_RELEASE_VERSION,
          sha256: "7d64246633ae094f67e3bbcd2d679e89048f91346d5339313336e7483f40f056",
        }],
        """
        mock_fetch.return_value = mock_ts.encode("utf-8")
        info = resolve_antigravity_acp()
        self.assertEqual(info.tool, "antigravity-acp")
        self.assertEqual(info.version, "1.4.5")
        self.assertEqual(info.args["ANTIGRAVITY_ACP_SHA256_AMD64"], "923923a0d7dc8073f66cc6f78647a3107e3a7ee2b7e1a24df8b3927b5188013b")
        self.assertEqual(info.args["ANTIGRAVITY_ACP_SHA256_ARM64"], "7d64246633ae094f67e3bbcd2d679e89048f91346d5339313336e7483f40f056")

    @patch("upstreams.github_release._fetch_json")
    @patch("upstreams.github_release.get_containerfile_args")
    def test_resolve_chromium(self, mock_args: MagicMock, mock_fetch: MagicMock) -> None:
        from upstreams.github_release import resolve_chromium

        mock_fetch.return_value = {
            "channels": {
                "Stable": {
                    "version": "157.0.8103.38",
                    "downloads": {
                        "chrome": [
                            {"platform": "linux64", "url": "https://example.com/linux64.zip"},
                            {"platform": "linux-arm64", "url": "https://example.com/linux-arm64.zip"},
                        ]
                    },
                }
            }
        }
        mock_args.return_value = {
            "CHROMIUM_VERSION": "157.0.8103.38",
            "CHROMIUM_SHA256_AMD64": "chromesha-amd64",
            "CHROMIUM_SHA256_ARM64": "chromesha-arm64",
        }
        info = resolve_chromium()
        self.assertEqual(info.tool, "chromium")
        self.assertEqual(info.version, "157.0.8103.38")
        self.assertEqual(info.args["CHROMIUM_SHA256_AMD64"], "chromesha-amd64")
        self.assertEqual(info.args["CHROMIUM_SHA256_ARM64"], "chromesha-arm64")

    @patch("upstreams.language_manifests._fetch_url")
    @patch("upstreams.language_manifests.get_containerfile_args")
    def test_resolve_python(self, mock_args: MagicMock, mock_fetch: MagicMock) -> None:
        import json
        from upstreams.language_manifests import resolve_python

        eol_json = json.dumps([{"cycle": "3.15", "latest": "3.15.2"}]).encode("utf-8")
        mock_fetch.return_value = eol_json
        mock_args.return_value = {
            "PYTHON_VERSION": "3.15.2",
            "PYTHON_SHA256": "pysha256",
        }
        info = resolve_python()
        self.assertEqual(info.tool, "python")
        self.assertEqual(info.version, "3.15.2")
        self.assertEqual(info.args["PYTHON_SHA256"], "pysha256")



if __name__ == "__main__":
    unittest.main()
