from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
import yaml
from pa_packages.git.host.git import (
    check_repo_gitignore,
    get_sanitized_git_config_json,
    read_git_config,
    resolve_git_hooks_mounts,
    warn_missing_gitignore,
)
from pa_packages.git.host.plugin import GitPlugin

from packages.manifest import ExtensionConfig, PackageManifest
from packages.plugin import ContainerRunSpec, RunContext

if TYPE_CHECKING:
    from pathlib import Path

sys.dont_write_bytecode = True


def _make_dummy_manifest() -> PackageManifest:
    return PackageManifest(
        name="git",
        version="2.56.0",
        schema_version="3.0.0",
        description="Fast, scalable distributed revision control",
        category="scm",
        extension=ExtensionConfig(entrypoint="host.plugin:GitPlugin", config_key="git"),
    )


class TestGitPlugin:
    def test_contribute_config_schema(self, tmp_path: Path):
        manifest = _make_dummy_manifest()
        plugin = GitPlugin(manifest, tmp_path)
        schema = plugin.contribute_config_schema()
        assert schema["type"] is dict
        assert "safe_directory" in schema["keys"]
        assert "rewrite_ssh_to_https" in schema["keys"]

    def test_on_run_init(self, tmp_path: Path):
        manifest = _make_dummy_manifest()
        pa_dir = tmp_path / ".pa-container"
        pa_dir.mkdir()
        (pa_dir / "config.yaml").write_text(
            yaml.dump(
                {
                    "packages": [
                        {
                            "git": {
                                "features": [],
                                "config": {"safe_directory": True, "rewrite_ssh_to_https": False},
                                "secrets": [],
                            }
                        }
                    ]
                }
            )
        )

        plugin = GitPlugin(manifest, tmp_path, project_dir=tmp_path)
        ctx = RunContext(
            project_dir=tmp_path,
            options=MagicMock(),
            config={},
            package_configs={"git": {"safe_directory": True, "rewrite_ssh_to_https": False}},
        )
        plugin.on_run_init(ctx)
        assert ctx.has_mode("git")
        assert ctx.get_attribute("git.config") == {"safe_directory": True, "rewrite_ssh_to_https": False}

    def test_on_preflight(self, tmp_path: Path):
        manifest = _make_dummy_manifest()
        plugin = GitPlugin(manifest, tmp_path, project_dir=tmp_path)
        ctx = RunContext(
            project_dir=tmp_path,
            options=MagicMock(),
            config={},  # type: ignore[arg-type]
        )
        with patch("pa_packages.git.host.plugin.warn_missing_gitignore") as mock_warn:
            plugin.on_preflight(ctx)
            mock_warn.assert_called_once()

    def test_on_container_configure(self, tmp_path: Path):
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        root_hook = pkg_dir / "container" / "entrypoint.d" / "root" / "20-git.sh"
        root_hook.parent.mkdir(parents=True)
        root_hook.write_text("#!/bin/bash\n")
        agent_hook = pkg_dir / "container" / "entrypoint.d" / "agent" / "20-git.sh"
        agent_hook.parent.mkdir(parents=True)
        agent_hook.write_text("#!/bin/bash\n")

        manifest = _make_dummy_manifest()
        proj_dir = tmp_path / "project"
        proj_dir.mkdir()
        git_dir = proj_dir / ".git"
        git_dir.mkdir()
        (git_dir / "hooks").mkdir()

        plugin = GitPlugin(manifest, pkg_dir, project_dir=proj_dir)
        plugin.git_cfg = {"safe_directory": True, "rewrite_ssh_to_https": True}
        spec = ContainerRunSpec()
        ctx = RunContext(
            project_dir=proj_dir,
            options=MagicMock(),
            config={  # type: ignore[arg-type]
                "security": {"read_only_git_hooks": True, "git_config_allowlist": ["user.name"]},
            },
        )
        with patch("pa_packages.git.host.plugin.get_sanitized_git_config_json", return_value='{"user.name": "Test"}'):
            plugin.on_container_configure(spec, ctx)

        assert spec.env["GIT_SAFE_DIRECTORY"] == "true"
        assert spec.env["GIT_REWRITE_SSH"] == "true"
        assert spec.env["HOST_GIT_CONFIG"] == '{"user.name": "Test"}'
        assert any(str(git_dir / "hooks") in arg for arg in spec.extra_run_args)
        assert any(str(root_hook) in arg for arg in spec.extra_run_args)
        assert any(str(agent_hook) in arg for arg in spec.extra_run_args)


class TestReadGitConfig:
    def test_missing_config_raises(self, tmp_path: Path):
        (tmp_path / "config.yaml").write_text("{}\n")
        with pytest.raises(ValueError, match="Missing required 'git' configuration section"):
            read_git_config(tmp_path)

    def test_explicit_false(self, tmp_path: Path):
        (tmp_path / "config.yaml").write_text(
            yaml.dump({"git": {"safe_directory": False, "rewrite_ssh_to_https": False}})
        )
        cfg = read_git_config(tmp_path)
        assert cfg == {"safe_directory": False, "rewrite_ssh_to_https": False}

    def test_string_boolean_values_raise(self, tmp_path: Path):
        (tmp_path / "config.yaml").write_text(yaml.dump({"git": {"safe_directory": "0", "rewrite_ssh_to_https": "1"}}))
        with pytest.raises(ValueError, match="Invalid 'git.safe_directory': expected bool"):
            read_git_config(tmp_path)


class TestGetSanitizedGitConfigJson:
    def test_sanitizes_url_credentials(self):
        mock_logger = MagicMock()
        output = "file:/home/user/.gitconfig\tremote.origin.url=https://user:pass@github.com/org/repo.git\n"
        with patch("subprocess.check_output", return_value=output):
            result = json.loads(get_sanitized_git_config_json(mock_logger))
        assert "user" not in result["remote.origin.url"]
        assert "pass" not in result["remote.origin.url"]
        assert result["remote.origin.url"] == "https://github.com/org/repo.git"

    def test_strips_credential_from_url(self):
        mock_logger = MagicMock()
        output = "credential.helper\tstore\n"
        with patch("subprocess.check_output", return_value=output):
            result = json.loads(get_sanitized_git_config_json(mock_logger))
        assert "credential.helper" not in result

    def test_skips_file_origin(self):
        mock_logger = MagicMock()
        output = (
            "file:.git/config\tuser.name=Test User\n"
            "file:/home/user/project/.git/config\tuser.email=local@example.com\n"
            "file:/home/user/.gitconfig\tuser.signingkey=GLOBALKEY\n"
        )
        with patch("subprocess.check_output", return_value=output):
            result = json.loads(get_sanitized_git_config_json(mock_logger))
        assert "user.name" not in result
        assert "user.email" not in result
        assert result.get("user.signingkey") == "GLOBALKEY"

    def test_returns_empty_dict_on_git_error(self):
        mock_logger = MagicMock()
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
            result = get_sanitized_git_config_json(mock_logger)
        assert result == "{}"

    def test_returns_empty_dict_on_missing_git(self):
        mock_logger = MagicMock()
        with patch("subprocess.check_output", side_effect=FileNotFoundError):
            result = get_sanitized_git_config_json(mock_logger)
        assert result == "{}"

    def test_filters_by_allowlist(self):
        mock_logger = MagicMock()
        output = (
            "file:/home/user/.gitconfig\tuser.name=Alice\n"
            "file:/home/user/.gitconfig\tuser.email=alice@example.com\n"
            "file:/home/user/.gitconfig\tcustom.setting=foobar\n"
        )
        allowlist = ["user.name", "user.email"]
        with patch("subprocess.check_output", return_value=output):
            result = json.loads(get_sanitized_git_config_json(mock_logger, allowlist=allowlist))
        assert result == {"user.name": "Alice", "user.email": "alice@example.com"}


class TestGitignoreWarnings:
    def test_check_repo_gitignore_missing_entries(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".gitignore").write_text("# empty\n")
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=str(tmp_path) + "\n"),
                subprocess.CompletedProcess(args=[], returncode=1),
            ]
            missing = check_repo_gitignore(tmp_path)
            assert ".pa-container/" in missing

    def test_warn_missing_gitignore_logs_warning_for_missing_entry(self, tmp_path: Path):
        mock_logger = MagicMock()
        with (
            patch("pa_packages.git.host.git.check_repo_gitignore", return_value=[".pa-container/"]),
            patch("pa_packages.git.host.git.check_repo_tracked_pa_container", return_value=[]),
        ):
            warn_missing_gitignore(tmp_path, mock_logger)
            assert "Recommended .gitignore entries are missing" in str(mock_logger.warning.call_args)

    def test_warn_missing_gitignore_logs_warning_for_tracked_files(self, tmp_path: Path):
        mock_logger = MagicMock()
        with (
            patch("pa_packages.git.host.git.check_repo_gitignore", return_value=[]),
            patch(
                "pa_packages.git.host.git.check_repo_tracked_pa_container", return_value=[".pa-container/config.yaml"]
            ),
        ):
            warn_missing_gitignore(tmp_path, mock_logger)
            assert "git rm -r --cached .pa-container" in str(mock_logger.warning.call_args)


class TestResolveGitHooksMounts:
    def test_directory_hooks_mount(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        mounts = resolve_git_hooks_mounts(tmp_path, read_only_hooks=True)
        assert mounts == ["--volume", f"{git_dir / 'hooks'}:/workspace/.git/hooks:ro"]

    def test_worktree_file_mount(self, tmp_path: Path):
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: /outside/path/to/gitdir\n")
        with patch("subprocess.check_output", return_value="/outside/path/to/gitdir/hooks\n"):
            mounts = resolve_git_hooks_mounts(tmp_path, read_only_hooks=True)
        assert mounts == ["--volume", f"{git_file}:/workspace/.git:ro"]

    def test_disabled_read_only_hooks(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        mounts = resolve_git_hooks_mounts(tmp_path, read_only_hooks=False)
        assert mounts == []
