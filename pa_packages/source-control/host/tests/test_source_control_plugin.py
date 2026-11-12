from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
import yaml

from packages.manifest import PackageManifest
from packages.plugin import ContainerRunSpec, RunContext

if TYPE_CHECKING:
    from pathlib import Path

from pa_packages.source_control.host.plugin import SourceControlPlugin
from pa_packages.source_control.host.source_control import (
    _probe_host_cli,
    mask_token,
    read_source_control_config,
    resolve_source_control_tokens,
)


class TestMaskToken:
    def test_empty_token(self) -> None:
        assert mask_token("") == ""

    def test_short_token(self) -> None:
        assert mask_token("abc") == "***"
        assert mask_token("12345678") == "***"

    def test_long_token(self) -> None:
        masked = mask_token("gho_1234567890abcdef")
        assert masked == "gho_...cdef"


class TestReadSourceControlConfig:
    def test_defaults_when_omitted(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text("{}\n")
        cfg = read_source_control_config(tmp_path)
        assert cfg["enabled"] is False
        assert cfg["auto_detect_host_cli"] is False
        assert cfg["setup_git_credentials"] is True
        assert cfg["providers"] == {}

    def test_explicit_settings(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "source_control": {
                        "enabled": True,
                        "auto_detect_host_cli": True,
                        "setup_git_credentials": False,
                        "providers": {"github": {"token": "ghp_123"}},
                    }
                }
            )
        )
        cfg = read_source_control_config(tmp_path)
        assert cfg["enabled"] is True
        assert cfg["auto_detect_host_cli"] is True
        assert cfg["setup_git_credentials"] is False
        assert cfg["providers"] == {"github": {"token": "ghp_123"}}

    def test_string_boolean_settings_raise(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "source_control": {
                        "enabled": "0",
                        "auto_detect_host_cli": "1",
                        "setup_git_credentials": "false",
                    }
                }
            )
        )
        with pytest.raises(ValueError, match="Invalid 'source_control.enabled': expected bool"):
            read_source_control_config(tmp_path)


class TestResolveSourceControlTokens:
    def test_returns_empty_when_disabled(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text(yaml.dump({"packages": []}))
        tokens = resolve_source_control_tokens(tmp_path)
        assert tokens == {}

    def test_ignores_host_environment_and_agent_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "packages": [{"source-control": {"features": ["github"], "config": {}, "secrets": []}}],
                    "agent": {
                        "env": {
                            "GH_TOKEN": "gho_untrusted_agent_env",
                            "GITLAB_TOKEN": "glpat_untrusted_agent_env",
                        }
                    },
                }
            )
        )
        monkeypatch.setenv("GH_TOKEN", "gho_untrusted_env")
        monkeypatch.setenv("GITHUB_TOKEN", "gho_untrusted_env")
        monkeypatch.setenv("GITEA_TOKEN", "gtea_untrusted_env")
        monkeypatch.setenv("AZURE_DEVOPS_EXT_PAT", "az_untrusted_env")

        tokens = resolve_source_control_tokens(tmp_path)
        assert tokens == {}

    def test_resolves_from_os_keyring(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "packages": [
                        {
                            "source-control": {
                                "features": ["github", "gitlab", "forgejo", "azure_devops", "bitbucket", "gitcafe"],
                                "config": {},
                                "secrets": [
                                    {"name": "github", "account": "GH_TOKEN"},
                                    {"name": "gitlab", "account": "GITLAB_TOKEN"},
                                    {"name": "forgejo", "account": "GITEA_TOKEN"},
                                    {"name": "azure_devops", "account": "AZURE_DEVOPS_EXT_PAT"},
                                    {"name": "bitbucket", "account": "BITBUCKET_TOKEN"},
                                    {"name": "gitcafe", "account": "GITCAFE_TOKEN"},
                                ],
                            }
                        }
                    ]
                }
            )
        )

        def mock_get_keyring(account: str, service: str = "pa-container") -> str | None:
            if account == "GH_TOKEN":
                return "gho_keyring_secret_token"
            if account == "GITLAB_TOKEN":
                return "glpat_keyring_secret_token"
            if account == "GITEA_TOKEN":
                return "gtea_keyring_secret_token"
            if account == "AZURE_DEVOPS_EXT_PAT":
                return "az_keyring_secret_token"
            if account == "BITBUCKET_TOKEN":
                return "bitbucket_keyring_secret_token"
            if account == "GITCAFE_TOKEN":
                return "cafe_keyring_secret_token"
            return None

        with patch("pa_packages.source_control.host.source_control.get_keyring_secret", side_effect=mock_get_keyring):
            tokens = resolve_source_control_tokens(tmp_path)

        assert tokens["GH_TOKEN"] == "gho_keyring_secret_token"
        assert tokens["GITLAB_TOKEN"] == "glpat_keyring_secret_token"
        assert tokens["GITEA_TOKEN"] == "gtea_keyring_secret_token"
        assert tokens["AZURE_DEVOPS_EXT_PAT"] == "az_keyring_secret_token"
        assert tokens["BITBUCKET_TOKEN"] == "bitbucket_keyring_secret_token"
        assert tokens["GITCAFE_TOKEN"] == "cafe_keyring_secret_token"

    def test_resolves_custom_keyring_var(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "packages": [
                        {
                            "source-control": {
                                "features": ["github"],
                                "config": {},
                                "secrets": [
                                    {"name": "github", "account": "PA_CONTAINER_T3_GH_TOKEN"},
                                ],
                            }
                        }
                    ]
                }
            )
        )

        def mock_get_keyring(account: str, service: str = "pa-container") -> str | None:
            if account == "PA_CONTAINER_T3_GH_TOKEN":
                return "gho_custom_keyring_token"
            return None

        with patch("pa_packages.source_control.host.source_control.get_keyring_secret", side_effect=mock_get_keyring):
            tokens = resolve_source_control_tokens(tmp_path)

        assert tokens["GH_TOKEN"] == "gho_custom_keyring_token"

    def test_cli_probe_skipped_when_auto_detect_false(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "packages": [
                        {
                            "source-control": {
                                "features": ["github"],
                                "config": {"auto_detect_host_cli": False},
                                "secrets": [{"name": "github", "account": "GH_TOKEN"}],
                            }
                        }
                    ]
                }
            )
        )

        with (
            patch("pa_packages.source_control.host.source_control.get_keyring_secret", return_value=None),
            patch("pa_packages.source_control.host.source_control._probe_host_cli") as mock_probe,
        ):
            with pytest.raises(ValueError, match="Required secret for 'github'"):
                resolve_source_control_tokens(tmp_path)
            assert mock_probe.call_count == 0

    def test_cli_probe_called_when_auto_detect_true(self, tmp_path: Path) -> None:
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "packages": [
                        {
                            "source-control": {
                                "features": ["github"],
                                "config": {"auto_detect_host_cli": True},
                                "secrets": [{"name": "github", "account": "GH_TOKEN"}],
                            }
                        }
                    ]
                }
            )
        )

        def mock_probe(cmd: tuple[str, ...]) -> str | None:
            if cmd == ("gh", "auth", "token"):
                return "gho_from_host_cli"
            return None

        with (
            patch("pa_packages.source_control.host.source_control.get_keyring_secret", return_value=None),
            patch("pa_packages.source_control.host.source_control._probe_host_cli", side_effect=mock_probe),
        ):
            tokens = resolve_source_control_tokens(tmp_path)
            assert tokens["GH_TOKEN"] == "gho_from_host_cli"

    def test_probe_host_cli_helper(self) -> None:
        with patch("shutil.which", return_value=None):
            assert _probe_host_cli(("gh", "auth", "token")) is None

        with patch("shutil.which", return_value="/usr/bin/gh"):
            mock_res = MagicMock(returncode=0, stdout="my_cli_token\n")
            with patch("subprocess.run", return_value=mock_res):
                assert _probe_host_cli(("gh", "auth", "token")) == "my_cli_token"

            mock_fail = MagicMock(returncode=1, stdout="")
            with patch("subprocess.run", return_value=mock_fail):
                assert _probe_host_cli(("gh", "auth", "token")) is None

            with patch("subprocess.run", side_effect=Exception("error")):
                assert _probe_host_cli(("gh", "auth", "token")) is None


def _make_dummy_manifest() -> PackageManifest:
    return PackageManifest(
        name="source-control",
        version="1.0.0",
        schema_version="3.0.0",
        description="test",
    )


class TestSourceControlPlugin:
    def test_contribute_config_schema(self, tmp_path: Path) -> None:
        manifest = _make_dummy_manifest()
        plugin = SourceControlPlugin(manifest, tmp_path)
        schema = plugin.contribute_config_schema()
        assert schema["type"] is dict
        assert "auto_detect_host_cli" in schema["keys"]
        assert "setup_git_credentials" in schema["keys"]

    def test_get_secret_mappings(self, tmp_path: Path) -> None:
        manifest = _make_dummy_manifest()
        plugin = SourceControlPlugin(manifest, tmp_path)

        # Disabled -> empty mappings
        cfg_disabled: Any = {"packages": []}
        assert plugin.get_secret_mappings(cfg_disabled) == []

        # Enabled -> mappings for providers
        cfg_enabled: Any = {
            "packages": [
                {
                    "source-control": {
                        "features": ["github", "gitlab", "forgejo", "azure_devops"],
                        "config": {},
                        "secrets": [
                            {"name": "github", "account": "GH_TOKEN"},
                            {"name": "gitlab", "account": "GITLAB_TOKEN"},
                            {"name": "forgejo", "account": "GITEA_TOKEN"},
                            {"name": "azure_devops", "account": "AZURE_DEVOPS_EXT_PAT"},
                        ],
                    }
                }
            ]
        }
        mappings = plugin.get_secret_mappings(cfg_enabled)
        names = {m.name for m in mappings}
        assert "github-token" in names
        assert "gitlab-token" in names
        assert "forgejo-token" in names
        assert "azure_devops-token" in names

    def test_lifecycle_hooks(self, tmp_path: Path) -> None:
        manifest = _make_dummy_manifest()
        plugin = SourceControlPlugin(manifest, tmp_path, project_dir=tmp_path)

        options = MagicMock()
        ctx = RunContext(
            project_dir=tmp_path,
            options=options,
            config={},
            package_configs={"source-control": {"setup_git_credentials": True}},
            package_secrets={"source-control": [{"name": "github", "account": "GH_TOKEN"}]},
        )

        def mock_get_keyring(account: str, service: str = "pa-container") -> str | None:
            if account == "GH_TOKEN":
                return "token_gh_secret"
            return None

        with patch("pa_packages.source_control.host.source_control.get_keyring_secret", side_effect=mock_get_keyring):
            plugin.on_run_init(ctx)

        assert ctx.has_mode("source-control")
        assert ctx.get_attribute("source_control.tokens") == {"GH_TOKEN": "token_gh_secret"}

        spec = ContainerRunSpec()
        plugin.on_container_configure(spec, ctx)

        assert spec.env["GH_TOKEN"] == "token_gh_secret"
        assert spec.env["SETUP_GIT_CREDENTIALS"] == "true"
