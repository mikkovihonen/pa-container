"""Tests for config_schema.py — per-project configuration validation."""

import subprocess
import sys
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

sys.dont_write_bytecode = True


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def valid_config(tmp_path: Path) -> Path:
    """Create a valid config.yaml with schema_version matching the test version."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "schema_version": "0.7.0",
                "resources": {
                    "agent": {"memory": "16g", "cpus": 8},
                    "proxy": {"memory": "4g", "cpus": 4},
                },
                "llama": {"startup_timeout": 180, "startup_attempts": 2},
                "network": {"ipv6": False, "dns": "1.1.1.1"},
                "proxy": {
                    "expose_ui": "localhost",
                    "max_view_flows": 2000,
                    "stream_large_bodies": "10m",
                    "open_browser": False,
                },
                "packages": [
                    {
                        "agents": {
                            "features": ["pi"],
                            "config": {},
                            "secrets": [],
                        }
                    }
                ],
                "agent": {
                    "env": {},
                    "mounts": [],
                    "read_only_pa_container": True,
                },
                "tmpfs": {"paths": []},
                "flow_export": {"enabled": False},
                "egress": {"allow": {}},
                "security": {
                    "read_only_git_hooks": True,
                    "blocked_mount_paths": [],
                    "blocked_ip_ranges": [],
                    "git_config_allowlist": [],
                },
                "logging": {
                    "log_level": "INFO",
                    "retention": {"max_days": 14, "max_launches": 10},
                },
            }
        )
    )
    return config_path


@pytest.fixture
def config_with_schema_version_only(tmp_path: Path) -> Path:
    """Create a config.yaml with only schema_version (missing required fields)."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"schema_version": "0.1.0"}))
    return config_path


@pytest.fixture
def config_without_schema_version(tmp_path: Path) -> Path:
    """Create a config.yaml without schema_version."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"resources": {"agent": {"memory": "16g", "cpus": 8}}}))
    return config_path


@pytest.fixture
def config_with_wrong_schema_version(tmp_path: Path) -> Path:
    """Create a config.yaml with a mismatched schema_version."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"schema_version": "9.9.9"}))
    return config_path


# ─── get_app_version tests ─────────────────────────────────────────────────


class TestGetAppVersion:
    """Tests for get_app_version()."""

    def test_returns_none_when_no_tags(self, tmp_path: Path):
        """When no git tags exist, get_app_version returns None."""
        from config_schema import get_app_version

        # Patch subprocess.run to simulate no tags
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "tag", "--sort=-v:refname", "--merged", "HEAD"],
                returncode=0,
                stdout="",
            )
            result = get_app_version()
        assert result is None

    def test_returns_version_from_tag(self, tmp_path: Path):
        """When a git tag exists, get_app_version returns the version without 'v' prefix."""
        from config_schema import get_app_version

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "tag", "--sort=-v:refname", "--merged", "HEAD"],
                returncode=0,
                stdout="v1.2.3\n",
            )
            result = get_app_version()
        assert result == "1.2.3"

    def test_handles_multiple_tags(self, tmp_path: Path):
        """When multiple tags exist, get_app_version returns the latest one."""
        from config_schema import get_app_version

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "tag", "--sort=-v:refname", "--merged", "HEAD"],
                returncode=0,
                stdout="v2.0.0\nv1.2.3\n",
            )
            result = get_app_version()
        assert result == "2.0.0"

    def test_returns_none_on_git_error(self, tmp_path: Path):
        """When git command fails, get_app_version returns None."""
        from config_schema import get_app_version

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "git")
            result = get_app_version()
        assert result is None


# ─── validate_config tests ─────────────────────────────────────────────────


class TestValidateConfig:
    """Tests for validate_config()."""

    def test_valid_config_passes(self, valid_config: Path):
        """A valid config passes validation."""
        from config_schema import validate_config

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, schema_version = validate_config(valid_config)
        assert is_valid is True
        assert errors == []
        assert schema_version == "0.7.0"

    def test_missing_config_file(self, tmp_path: Path):
        """When config.yaml doesn't exist, validation fails."""
        from config_schema import validate_config

        config_path = tmp_path / "nonexistent" / "config.yaml"
        is_valid, errors, _ = validate_config(config_path)
        assert is_valid is False
        assert any("not found" in e for e in errors)

    def test_missing_schema_version(self, config_without_schema_version: Path):
        """When schema_version is missing, validation fails."""
        from config_schema import validate_config

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(config_without_schema_version)
        assert is_valid is False
        assert any("schema_version" in e and "missing" in e for e in errors)

    def test_schema_version_mismatch(self, config_with_wrong_schema_version: Path):
        """When schema_version doesn't match app version, validation fails."""
        from config_schema import validate_config

        with patch("config_schema.get_app_version", return_value="1.0.0"):
            is_valid, errors, schema_version = validate_config(config_with_wrong_schema_version)
        assert is_valid is False
        assert any("mismatch" in e for e in errors)
        assert schema_version == "9.9.9"

    def test_schema_version_match(self, valid_config: Path):
        """When schema_version matches app version, validation passes (if schema is valid)."""
        from config_schema import validate_config

        with patch("config_schema.get_app_version", return_value="0.7.0"):
            is_valid, errors, schema_version = validate_config(valid_config)
        assert is_valid is True
        assert schema_version == "0.7.0"

    def test_missing_required_fields(self, config_with_schema_version_only: Path):
        """When required fields are missing, validation fails."""
        from config_schema import validate_config

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(config_with_schema_version_only)
        assert is_valid is False
        # Should have errors for missing resources, llama, network, etc.
        assert len(errors) > 1

    def test_wrong_type_for_field(self, tmp_path: Path):
        """When a field has the wrong type, validation fails."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "schema_version": "0.1.0",
                    "resources": {
                        "agent": {"memory": 123, "cpus": 8},  # memory should be str
                    },
                    "llama": {"startup_timeout": 180, "startup_attempts": 2},
                    "network": {"ipv6": False, "dns": "1.1.1.1"},
                    "proxy": {"expose_ui": "localhost"},
                    "agents": {"enabled": ["pi"], "default": "pi"},
                    "agent": {"env": {}, "mounts": []},
                    "nested_containers": {
                        "enabled": False,
                        "storage": "volume",
                        "security": "disable",
                        "ports": {"expose": "localhost", "publish": []},
                    },
                    "tmpfs": {"paths": []},
                    "flow_export": {"enabled": False},
                    "egress": {"allow": {}},
                }
            )
        )

        from config_schema import validate_config

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(config_path)
        assert is_valid is False
        assert any("expected" in e and "memory" in e for e in errors)

    def test_invalid_yaml(self, tmp_path: Path):
        """When config.yaml is invalid YAML, validation fails."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("invalid: yaml: content: [")

        from config_schema import validate_config

        is_valid, errors, _ = validate_config(config_path)
        assert is_valid is False
        assert any("YAML" in e for e in errors)


class TestLegacyNestedContainersRejected:
    """The root-level nested_containers section is rejected with fatal error."""

    def test_legacy_nested_containers_rejected(self, valid_config: Path):
        import yaml as _yaml

        from config_schema import validate_config

        data = _yaml.safe_load(valid_config.read_text())
        data["nested_containers"] = {
            "enabled": False,
            "storage": "volume",
            "security": "disable",
            "ports": {"expose": "localhost", "publish": []},
        }
        valid_config.write_text(_yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("Legacy root-level configuration section 'nested_containers' is not allowed" in e for e in errors)

    def test_podman_package_config_valid(self, valid_config: Path):
        import yaml as _yaml

        from config_schema import validate_config

        data = _yaml.safe_load(valid_config.read_text())
        data["packages"].append(
            {
                "podman": {
                    "features": [],
                    "config": {
                        "storage": "volume",
                        "security": "disable",
                        "ports": {"expose": "localhost", "publish": []},
                    },
                    "secrets": [],
                }
            }
        )
        valid_config.write_text(_yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is True
        assert errors == []


class TestValidateModels:
    """Tests for validate_models() in config_schema.py."""

    def _write_models(self, tmp_path: Path, content: str, filename: str = "models.yaml") -> Path:
        """Write a models.yaml file and return its path."""
        models_path = tmp_path / filename
        models_path.write_text(content)
        return models_path

    def test_valid_models_strings_passes(self, tmp_path: Path):
        """When models.yaml contains an allow list of strings, validation passes."""
        from config_schema import validate_models

        content = "allow:\n  - qwen\n  - opper/claude\n"
        p = self._write_models(tmp_path, content)
        is_valid, errors = validate_models(p)
        assert is_valid is True
        assert errors == []

    def test_valid_models_dicts_and_default_passes(self, tmp_path: Path):
        """When models.yaml has default and dict items in allow list with id, validation passes."""
        from config_schema import validate_models

        content = "default: qwen\nallow:\n  - id: qwen\n  - id: opper/claude\n  - id: gemma\n"
        p = self._write_models(tmp_path, content)
        is_valid, errors = validate_models(p)
        assert is_valid is True
        assert errors == []

    def test_yml_suffix_rejected(self, tmp_path: Path):
        """When models file uses .yml extension, validation fails."""
        from config_schema import validate_models

        p = self._write_models(tmp_path, "allow:\n  - qwen\n", filename="models.yml")
        is_valid, errors = validate_models(p)
        assert is_valid is False
        assert any("must be a YAML file (.yaml)" in e for e in errors)

    def test_file_not_found(self, tmp_path: Path):
        """When models file does not exist, validation fails."""
        from config_schema import validate_models

        is_valid, errors = validate_models(tmp_path / "missing.yaml")
        assert is_valid is False
        assert any("not found" in e for e in errors)

    def test_non_yaml_suffix_rejected(self, tmp_path: Path):
        """When models file does not have .yaml extension, validation fails."""
        from config_schema import validate_models

        p = self._write_models(tmp_path, '{"allow": ["qwen"]}', filename="models.json")
        is_valid, errors = validate_models(p)
        assert is_valid is False
        assert any("must be a YAML file (.yaml)" in e for e in errors)

    def test_invalid_yaml(self, tmp_path: Path):
        """When models.yaml has syntax errors, validation fails."""
        from config_schema import validate_models

        p = self._write_models(tmp_path, "allow: [unclosed")
        is_valid, errors = validate_models(p)
        assert is_valid is False
        assert any("not valid YAML" in e for e in errors)

    def test_duplicate_keys_rejected(self, tmp_path: Path):
        """When models.yaml has duplicate mapping keys, validation fails."""
        from config_schema import validate_models

        content = "allow:\n  - qwen\nallow:\n  - gemma\n"
        p = self._write_models(tmp_path, content)
        is_valid, errors = validate_models(p)
        assert is_valid is False
        assert any("duplicate key 'allow'" in e for e in errors)

    def test_non_dict_yaml(self, tmp_path: Path):
        """When models.yaml is not a mapping, validation fails."""
        from config_schema import validate_models

        p = self._write_models(tmp_path, "- item1\n- item2\n")
        is_valid, errors = validate_models(p)
        assert is_valid is False
        assert any("must be a YAML mapping" in e for e in errors)

    def test_missing_allow_key(self, tmp_path: Path):
        """When models.yaml has no allow key, validation fails."""
        from config_schema import validate_models

        p = self._write_models(tmp_path, "default: qwen\n")
        is_valid, errors = validate_models(p)
        assert is_valid is False
        assert any("allow: required field missing" in e for e in errors)

    def test_allow_not_a_list(self, tmp_path: Path):
        """When allow is not a list, validation fails."""
        from config_schema import validate_models

        p = self._write_models(tmp_path, "allow: not-a-list\n")
        is_valid, errors = validate_models(p)
        assert is_valid is False
        assert any("allow: expected" in e and "list" in e for e in errors)

    def test_allow_empty_list(self, tmp_path: Path):
        """When allow list is empty, validation fails."""
        from config_schema import validate_models

        p = self._write_models(tmp_path, "allow: []\n")
        is_valid, errors = validate_models(p)
        assert is_valid is False
        assert any("list must not be empty" in e for e in errors)

    def test_allow_empty_string_item(self, tmp_path: Path):
        """When allow contains an empty or whitespace string, validation fails."""
        from config_schema import validate_models

        p = self._write_models(tmp_path, 'allow:\n  - "   "\n')
        is_valid, errors = validate_models(p)
        assert is_valid is False
        assert any("must not be empty string" in e for e in errors)

    def test_allow_dict_item_missing_id(self, tmp_path: Path):
        """When an allow dict item is missing id, validation fails."""
        from config_schema import validate_models

        p = self._write_models(tmp_path, "allow:\n  - other: val\n")
        is_valid, errors = validate_models(p)
        assert is_valid is False
        assert any("expected non-empty 'id' string" in e for e in errors)

    def test_allow_invalid_item_type(self, tmp_path: Path):
        """When allow item is not string or dict, validation fails."""
        from config_schema import validate_models

        p = self._write_models(tmp_path, "allow:\n  - 12345\n")
        is_valid, errors = validate_models(p)
        assert is_valid is False
        assert any("expected string or dict, got int" in e for e in errors)

    def test_allow_agent_native_gateway_valid(self, tmp_path: Path):
        """Agent-native gateways pass validation as simple strings or dicts without keyring fields."""
        from config_schema import validate_models

        gw_dir = tmp_path / "gateways"
        gw_dir.mkdir(parents=True)
        (gw_dir / "anthropic-account.yaml").write_text(
            "id: anthropic-account\ntype: anthropic\nbaseUrl: https://api.anthropic.com/v1\nauth:\n  type: agent-native\n"
        )
        p = self._write_models(tmp_path, "allow:\n  - anthropic-account\n")
        is_valid, errors = validate_models(p, gateways_dir=gw_dir)
        assert is_valid is True
        assert errors == []

    def test_allow_agent_native_duplicate_rejected(self, tmp_path: Path):
        """Agent-native gateways can only be instantiated once per provider."""
        from config_schema import validate_models

        gw_dir = tmp_path / "gateways"
        gw_dir.mkdir(parents=True)
        (gw_dir / "anthropic-account.yaml").write_text(
            "id: anthropic-account\ntype: anthropic\nbaseUrl: https://api.anthropic.com/v1\nauth:\n  type: agent-native\n"
        )
        p = self._write_models(tmp_path, "allow:\n  - anthropic-account\n  - id: anthropic-account\n")
        is_valid, errors = validate_models(p, gateways_dir=gw_dir)
        assert is_valid is False
        assert any("can only be instantiated once per provider" in e for e in errors)


class TestModelDefinitionValidation:
    """Tests for validate_model_def_data in schema_common.py."""

    def test_valid_model_def_data(self):
        from schema_common import validate_model_def_data

        data = {
            "hfModels": {
                "main": {
                    "fileFlag": "--model",
                    "repo": "org/repo",
                    "file": "model.gguf",
                }
            },
            "flags": ["--ctx-size", 4096],
        }
        errors = validate_model_def_data(data, model_id="test-model")
        assert errors == []

    def test_hf_models_null(self):
        from schema_common import validate_model_def_data

        errors = validate_model_def_data({"hfModels": None}, model_id="test")
        assert any("hfModels must not be null" in e for e in errors)

    def test_hf_models_not_dict(self):
        from schema_common import validate_model_def_data

        errors = validate_model_def_data({"hfModels": "not-a-dict"}, model_id="test")
        assert any("hfModels expected dict" in e for e in errors)

    def test_hf_models_empty(self):
        from schema_common import validate_model_def_data

        errors = validate_model_def_data({"hfModels": {}}, model_id="test")
        assert any("hfModels must not be empty" in e for e in errors)

    def test_hf_models_missing_main(self):
        from schema_common import validate_model_def_data

        errors = validate_model_def_data({"hfModels": {"draft": {}}}, model_id="test")
        assert any("hfModels.main is required" in e for e in errors)

    def test_hf_models_missing_required_fields(self):
        from schema_common import validate_model_def_data

        data = {
            "hfModels": {
                "main": {
                    "fileFlag": "--model",
                    # Missing: repo, file
                }
            }
        }
        errors = validate_model_def_data(data, model_id="test")
        assert any("repo must be a non-empty string" in e for e in errors)
        assert any("file must be a non-empty string" in e for e in errors)

    def test_flags_invalid_item_type(self):
        from schema_common import validate_model_def_data

        data = {
            "hfModels": {
                "main": {
                    "fileFlag": "--model",
                    "repo": "r",
                    "file": "f",
                }
            },
            "flags": ["--ctx-size", 4096, None],
        }
        errors = validate_model_def_data(data, model_id="test")
        assert any("flags[2] expected str/int/float, got NoneType" in e for e in errors)


class TestChatTemplatePaths:
    """Tests for check_chat_template_paths and resolve_chat_template_path in template_paths.py."""

    def test_valid_chat_template_path(self, tmp_path: Path):
        from template_paths import check_chat_template_paths

        template_file = tmp_path / "template.jinja"
        template_file.write_text("jinja")

        flags = ["--chat-template-file", str(template_file)]
        errors = check_chat_template_paths(flags, repo_root=tmp_path)
        assert errors == []

    def test_relative_chat_template_path(self, tmp_path: Path):
        from template_paths import check_chat_template_paths

        rel_path = "templates/chat.jinja"
        full_path = tmp_path / "coding-agent" / "default" / "global" / "chat-templates" / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text("jinja")

        flags = ["--chat-template-file", rel_path]
        errors = check_chat_template_paths(flags, repo_root=tmp_path)
        assert errors == []

    def test_global_chat_template_path(self, tmp_path: Path):
        from template_paths import check_chat_template_paths, resolve_chat_template_path

        global_dir = tmp_path / "global_templates"
        tpl_dir = global_dir / "Qwen"
        tpl_dir.mkdir(parents=True)
        tpl_file = tpl_dir / "chat_template.jinja"
        tpl_file.write_text("global jinja")

        flags = ["--chat-template-file", "Qwen/chat_template.jinja"]
        errors = check_chat_template_paths(flags, global_templates_dir=global_dir)
        assert errors == []

        resolved = resolve_chat_template_path("Qwen/chat_template.jinja", global_templates_dir=global_dir)
        assert resolved == tpl_file

    def test_missing_path_value(self, tmp_path: Path):
        from template_paths import check_chat_template_paths

        flags = ["--chat-template-file"]
        errors = check_chat_template_paths(flags, repo_root=tmp_path)
        assert any("has no following path" in e for e in errors)

    def test_non_string_path(self, tmp_path: Path):
        from template_paths import check_chat_template_paths

        flags = ["--chat-template-file", 12345]
        errors = check_chat_template_paths(flags, repo_root=tmp_path)
        assert any("path is not a string" in e for e in errors)

    def test_legacy_path_resolution_rejected(self, tmp_path: Path):
        from template_paths import check_chat_template_paths, resolve_chat_template_path

        global_dir = tmp_path / "chat-templates"
        tpl_dir = global_dir / "Qwen3.6-35B-A3B-UD-Q6_K-XL"
        tpl_dir.mkdir(parents=True)
        tpl_file = tpl_dir / "chat_template.jinja"
        tpl_file.write_text("jinja content")

        legacy_path = "/nonexistent/old-name/chat-templates/Qwen3.6-35B-A3B-UD-Q6_K-XL/chat_template.jinja"
        flags = ["--chat-template-file", legacy_path]
        errors = check_chat_template_paths(flags, global_templates_dir=global_dir)
        assert any("does not exist" in e for e in errors)

        with pytest.raises(FileNotFoundError):
            resolve_chat_template_path(legacy_path, global_templates_dir=global_dir)

    def test_nonexistent_file(self, tmp_path: Path):
        from template_paths import check_chat_template_paths

        flags = ["--chat-template-file", "missing/chat.jinja"]
        errors = check_chat_template_paths(flags, repo_root=tmp_path)
        assert any("path does not exist" in e for e in errors)


class TestVolumesSchema:
    def test_valid_volumes_config(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["volumes"] = {"paths": ["/workspace/node_modules", "/workspace/.venv"]}
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is True
        assert errors == []

    def test_invalid_volumes_type(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["volumes"] = "invalid_string"
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("volumes" in e for e in errors)


class TestAgentReadOnlyPiContainerSchema:
    def test_valid_read_only_pa_container_boolean(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["agent"]["read_only_pa_container"] = True
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is True
        assert errors == []

    def test_invalid_read_only_pa_container_string_and_int(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["agent"]["read_only_pa_container"] = "false"
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("agent.read_only_pa_container: expected bool" in e for e in errors)

        data["agent"]["read_only_pa_container"] = 0
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("agent.read_only_pa_container: expected bool" in e for e in errors)

    def test_invalid_read_only_pa_container_type(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["agent"]["read_only_pa_container"] = ["not", "a", "bool"]
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("read_only_pa_container" in e for e in errors)


class TestSecuritySchema:
    def test_valid_security_section(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["security"] = {
            "read_only_git_hooks": True,
            "blocked_mount_paths": ["~/.ssh", "~/.aws"],
            "blocked_ip_ranges": ["127.0.0.0/8", "10.0.0.0/8"],
            "git_config_allowlist": ["user.name", "user.email"],
        }
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is True
        assert errors == []

    def test_invalid_security_types(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["security"] = {
            "read_only_git_hooks": ["not_a_bool"],
            "blocked_mount_paths": "not_a_list",
        }
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("read_only_git_hooks" in e for e in errors)
        assert any("blocked_mount_paths" in e for e in errors)


class TestPackagesSchema:
    def test_valid_packages_section(self, valid_config: Path):
        from config_schema import validate_config
        from packages import discover_packages

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        pkgs = []
        for name in sorted(discover_packages().keys()):
            secrets = []
            if name == "source-control":
                secrets = [
                    {"name": "github", "account": "ACC"},
                    {"name": "gitlab", "account": "ACC"},
                    {"name": "forgejo", "account": "ACC"},
                    {"name": "azure_devops", "account": "ACC"},
                    {"name": "bitbucket", "account": "ACC"},
                    {"name": "gitcafe", "account": "ACC"},
                ]
            features = ["pi"] if name == "agents" else (["github"] if name == "source-control" else [])
            pkgs.append({name: {"features": features, "config": {}, "secrets": secrets}})
        data["packages"] = pkgs
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is True
        assert errors == []

    def test_empty_packages(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["packages"] = []
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("must include at least one agent package" in e for e in errors)

    def test_unknown_package_rejected(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["packages"] = [{"unknown_pkg": {"features": [], "config": {}, "secrets": []}}]
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("unknown package 'unknown_pkg'" in e for e in errors)

    def test_bare_string_package_rejected(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["packages"] = ["git"]
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("Canonical Package Specification" in e for e in errors)

    def test_shorthand_list_package_rejected(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["packages"] = [{"agents": ["pi"]}]
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("Canonical Package Specification" in e for e in errors)

    def test_secret_missing_account_rejected(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["packages"] = [
            {
                "agents": {
                    "features": ["pi"],
                    "config": {},
                    "secrets": [{"name": "key"}],
                }
            }
        ]
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("missing required field 'account'" in e for e in errors)

    def test_unmapped_required_secret_slot_rejected(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["packages"].append(
            {
                "source-control": {
                    "features": ["github"],
                    "config": {},
                    "secrets": [],
                }
            }
        )
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("unmapped required secret 'github'" in e for e in errors)

    def test_invalid_packages_types(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["packages"] = "not_a_list"
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("packages: expected list" in e for e in errors)

        data["packages"] = [123]
        valid_config.write_text(yaml.dump(data))
        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("expected dict item" in e for e in errors)

    def test_duplicate_key_error_handling(self, tmp_path: Path):
        from config_schema import validate_config

        p = tmp_path / "config.yaml"
        p.write_text("agent:\n  mode: cli\nagent:\n  mode: t3\n")
        is_valid, errors, _ = validate_config(p)
        assert is_valid is False
        assert any("duplicate key" in e.lower() for e in errors)

    def test_validate_project_yaml(self, tmp_path: Path):
        from config_schema import validate_project_yaml

        (tmp_path / "config.yaml").write_text("foo: 1\nfoo: 2\n")
        (tmp_path / "allowlist.yaml").write_text("bar: 1\n")
        (tmp_path / "token_replacer.yaml").write_text("baz: 1\n")

        errors = validate_project_yaml(tmp_path)
        assert len(errors) == 1
        assert "duplicate key" in errors[0].lower()

    def test_legacy_git_section_rejected(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["git"] = {"safe_directory": True}
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("Legacy root-level configuration section 'git' is not allowed" in e for e in errors)

    def test_git_package_config_valid(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["packages"].append(
            {
                "git": {
                    "features": [],
                    "config": {"safe_directory": True, "rewrite_ssh_to_https": False},
                    "secrets": [],
                }
            }
        )
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is True
        assert errors == []

    def test_legacy_source_control_section_rejected(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["source_control"] = {"enabled": True}
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("Legacy root-level configuration section 'source_control' is not allowed" in e for e in errors)

    def test_required_feature_with_at_least_one_selected(self, tmp_path: Path):
        from config_schema import validate_config
        from packages import discover_packages
        from packages.manifest import load_package_manifest

        pkg_dir = tmp_path / "pa_packages" / "req-feats"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.yaml").write_text(
            """schema_version: "0.7.0"
name: "req-feats"
version: "1.0.0"
category: "agents"
payload:
    type: distro_package
    packages:
        - "coreutils"
features:
    required: true
    alpha:
        description: "Alpha feature"
        default: false
    beta:
        description: "Beta feature"
        default: false
"""
        )
        real_pkgs = discover_packages()
        real_pkgs["req-feats"] = load_package_manifest(pkg_dir / "package.yaml")

        with patch("config_schema.discover_packages", return_value=real_pkgs):
            config_path = tmp_path / "config.yaml"
            config_path.write_text(
                yaml.dump(
                    {
                        "schema_version": "0.7.0",
                        "resources": {"agent": {"memory": "16g", "cpus": 8}, "proxy": {"memory": "4g", "cpus": 4}},
                        "llama": {"startup_timeout": 180, "startup_attempts": 2},
                        "network": {"ipv6": False, "dns": "1.1.1.1"},
                        "proxy": {"expose_ui": "localhost", "max_view_flows": 2000, "stream_large_bodies": "10m", "open_browser": False},
                        "packages": [{"req-feats": {"features": ["alpha"], "config": {}, "secrets": []}}],
                        "agent": {"env": {}, "mounts": [], "read_only_pa_container": True},
                        "tmpfs": {"paths": []},
                        "flow_export": {"enabled": False},
                        "egress": {"allow": {}},
                        "security": {"read_only_git_hooks": True, "blocked_mount_paths": [], "blocked_ip_ranges": [], "git_config_allowlist": []},
                        "logging": {"log_level": "INFO", "retention": {"max_days": 14, "max_launches": 10}},
                    }
                )
            )
            is_valid, errors, _ = validate_config(config_path)
        assert is_valid is True
        assert errors == []

    def test_required_feature_with_empty_features_fails(self, tmp_path: Path):
        from config_schema import validate_config
        from packages import discover_packages
        from packages.manifest import load_package_manifest

        pkg_dir = tmp_path / "pa_packages" / "req-feats-empty"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.yaml").write_text(
            """schema_version: "0.7.0"
name: "req-feats-empty"
version: "1.0.0"
category: "agents"
payload:
    type: distro_package
    packages:
        - "coreutils"
features:
    required: true
    alpha:
        description: "Alpha feature"
        default: false
    beta:
        description: "Beta feature"
        default: false
"""
        )
        real_pkgs = discover_packages()
        real_pkgs["req-feats-empty"] = load_package_manifest(pkg_dir / "package.yaml")

        with patch("config_schema.discover_packages", return_value=real_pkgs):
            config_path = tmp_path / "config.yaml"
            config_path.write_text(
                yaml.dump(
                    {
                        "schema_version": "0.7.0",
                        "resources": {"agent": {"memory": "16g", "cpus": 8}, "proxy": {"memory": "4g", "cpus": 4}},
                        "llama": {"startup_timeout": 180, "startup_attempts": 2},
                        "network": {"ipv6": False, "dns": "1.1.1.1"},
                        "proxy": {"expose_ui": "localhost", "max_view_flows": 2000, "stream_large_bodies": "10m", "open_browser": False},
                        "packages": [{"req-feats-empty": {"features": [], "config": {}, "secrets": []}}],
                        "agent": {"env": {}, "mounts": [], "read_only_pa_container": True},
                        "tmpfs": {"paths": []},
                        "flow_export": {"enabled": False},
                        "egress": {"allow": {}},
                        "security": {"read_only_git_hooks": True, "blocked_mount_paths": [], "blocked_ip_ranges": [], "git_config_allowlist": []},
                        "logging": {"log_level": "INFO", "retention": {"max_days": 14, "max_launches": 10}},
                    }
                )
            )
            is_valid, errors, _ = validate_config(config_path)
        assert is_valid is False
        assert any("this package requires at least one feature" in e for e in errors)
        assert any("req-feats-empty" in e for e in errors)

    def test_required_feature_with_unknown_feature_fails_first(self, tmp_path: Path):
        from config_schema import validate_config
        from packages import discover_packages
        from packages.manifest import load_package_manifest

        pkg_dir = tmp_path / "pa_packages" / "req-feats-unknown"
        pkg_dir.mkdir(parents=True)
        (pkg_dir / "package.yaml").write_text(
            """schema_version: "0.7.0"
name: "req-feats-unknown"
version: "1.0.0"
category: "agents"
payload:
    type: distro_package
    packages:
        - "coreutils"
features:
    required: true
    alpha:
        description: "Alpha feature"
        default: false
"""
        )
        real_pkgs = discover_packages()
        real_pkgs["req-feats-unknown"] = load_package_manifest(pkg_dir / "package.yaml")

        with patch("config_schema.discover_packages", return_value=real_pkgs):
            config_path = tmp_path / "config.yaml"
            config_path.write_text(
                yaml.dump(
                    {
                        "schema_version": "0.7.0",
                        "resources": {"agent": {"memory": "16g", "cpus": 8}, "proxy": {"memory": "4g", "cpus": 4}},
                        "llama": {"startup_timeout": 180, "startup_attempts": 2},
                        "network": {"ipv6": False, "dns": "1.1.1.1"},
                        "proxy": {"expose_ui": "localhost", "max_view_flows": 2000, "stream_large_bodies": "10m", "open_browser": False},
                        "packages": [{"req-feats-unknown": {"features": ["nonexistent"], "config": {}, "secrets": []}}],
                        "agent": {"env": {}, "mounts": [], "read_only_pa_container": True},
                        "tmpfs": {"paths": []},
                        "flow_export": {"enabled": False},
                        "egress": {"allow": {}},
                        "security": {"read_only_git_hooks": True, "blocked_mount_paths": [], "blocked_ip_ranges": [], "git_config_allowlist": []},
                        "logging": {"log_level": "INFO", "retention": {"max_days": 14, "max_launches": 10}},
                    }
                )
            )
            is_valid, errors, _ = validate_config(config_path)
        assert is_valid is False
        assert any("unknown feature 'nonexistent'" in e for e in errors)


class TestAgentsSchema:
    """Tests for the agents configuration section elimination and package rules."""

    def test_agents_section_is_obsolete(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["agents"] = {"enabled": ["pi"], "default": "pi"}
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("'agents' section is obsolete in schema 3.0.0" in e for e in errors)

    def test_packages_missing_agent_fails(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["packages"] = [{"git": {"features": [], "config": {}, "secrets": []}}]
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("configuration must include at least one agent package" in e for e in errors)

    def test_proxy_open_browser_valid(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["proxy"]["open_browser"] = True
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is True
        assert errors == []


class TestDesktopSchema:
    """The root-level desktop section is obsolete and rejected; virtual-desktop package is used instead."""

    def test_legacy_desktop_section_rejected(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["desktop"] = {"enabled": True}
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is False
        assert any("Legacy root-level configuration section 'desktop' is not allowed" in e for e in errors)

    def test_desktop_package_config_valid(self, valid_config: Path):
        from config_schema import validate_config

        with valid_config.open("r") as f:
            data = yaml.safe_load(f)
        data["packages"].append(
            {
                "virtual-desktop": {
                    "features": [],
                    "config": {
                        "resolution": "1920x1080",
                        "compositor": "labwc",
                        "open_browser": False,
                        "vnc": {"enabled": True, "port": 5900, "expose": "localhost"},
                        "novnc": {"enabled": True, "port": 6080, "expose": "localhost"},
                        "gpu": {"enabled": "auto"},
                    },
                    "secrets": [],
                }
            }
        )
        valid_config.write_text(yaml.dump(data))

        with patch("config_schema.get_app_version", return_value=None):
            is_valid, errors, _ = validate_config(valid_config)
        assert is_valid is True
        assert errors == []
