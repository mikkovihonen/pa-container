from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_schema import SCHEMA_VERSION_MISMATCH, validate_global_config
from config_types import GlobalConfig
from global_config import ensure_global_config, load_global_config


class TestGlobalConfigSeeding:
    def test_ensure_global_config_seeds_template(self, tmp_path: Path):
        repo_root = Path(__file__).resolve().parent.parent.parent
        target_dir = tmp_path / ".config" / "pi-container"
        target_file = ensure_global_config(config_dir=target_dir, repo_root=repo_root)

        assert target_file.exists()
        assert target_file == target_dir / "config.yaml"
        assert (target_dir / "models").is_dir()
        assert (target_dir / "gateways").is_dir()
        assert (target_dir / "chat-templates").is_dir()

        # Idempotent
        again = ensure_global_config(config_dir=target_dir, repo_root=repo_root)
        assert again == target_file

    def test_ensure_global_config_missing_template_raises(self, tmp_path: Path):
        fake_repo = tmp_path / "fake_repo"
        fake_repo.mkdir()
        target_dir = tmp_path / ".config" / "pi-container"
        with pytest.raises(FileNotFoundError, match="Global configuration template not found"):
            ensure_global_config(config_dir=target_dir, repo_root=fake_repo)


class TestLoadGlobalConfig:
    def test_load_seeded_config(self, tmp_path: Path):
        repo_root = Path(__file__).resolve().parent.parent.parent
        target_dir = tmp_path / ".config" / "pi-container"
        target_file = ensure_global_config(config_dir=target_dir, repo_root=repo_root)

        cfg = load_global_config(config_file=target_file, repo_root=repo_root)
        assert isinstance(cfg, GlobalConfig)
        assert cfg.schema_version == "0.6.6"
        assert cfg.runtime.log_level == "INFO"
        assert cfg.runtime.proxy_upstream_network == "podman"
        assert cfg.llama.build.repo == "https://github.com/ggml-org/llama.cpp.git"
        assert cfg.llama.build.tag == "v0.9.0"
        assert cfg.llama.build.minimal is True
        assert cfg.build.images.agent == "pi-coding-agent:local"
        assert cfg.build.dns == "1.1.1.1"

    def test_canonical_env_overrides(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        repo_root = Path(__file__).resolve().parent.parent.parent
        target_dir = tmp_path / ".config" / "pi-container"
        target_file = ensure_global_config(config_dir=target_dir, repo_root=repo_root)

        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("BRIDGE_INTERFACE", "br0")
        monkeypatch.setenv("PROXY_UPSTREAM_NETWORK", "custom_net")
        monkeypatch.setenv("LLAMA_BIN", "/custom/bin/llama-server")
        monkeypatch.setenv("LLAMA_BUILD_REPO", "https://github.com/custom/llama.cpp.git")
        monkeypatch.setenv("LLAMA_BUILD_TAG", "b9999")
        monkeypatch.setenv("LLAMA_BUILD_BACKEND", "cuda")
        monkeypatch.setenv("LLAMA_BUILD_MINIMAL", "false")
        monkeypatch.setenv("PI_IMAGE_TAG", "custom-agent:latest")
        monkeypatch.setenv("PROXY_IMAGE_TAG", "custom-proxy:latest")
        monkeypatch.setenv("BUILDER_IMAGE_TAG", "custom-builder:latest")
        monkeypatch.setenv("BUILD_DNS", "8.8.8.8")
        monkeypatch.setenv("PYTHON_OPTIMIZE", "0")
        monkeypatch.setenv("PI_MEMORY_PREFLIGHT", "0")
        monkeypatch.setenv("NODE_SOURCE", "build")

        cfg = load_global_config(config_file=target_file, repo_root=repo_root)
        assert cfg.runtime.log_level == "DEBUG"
        assert cfg.runtime.bridge_interface == "br0"
        assert cfg.runtime.proxy_upstream_network == "custom_net"
        assert cfg.llama.bin == "/custom/bin/llama-server"
        assert cfg.llama.build.repo == "https://github.com/custom/llama.cpp.git"
        assert cfg.llama.build.tag == "b9999"
        assert cfg.llama.build.backend == "cuda"
        assert cfg.llama.build.minimal is False
        assert cfg.build.images.agent == "custom-agent:latest"
        assert cfg.build.images.proxy == "custom-proxy:latest"
        assert cfg.build.images.builder == "custom-builder:latest"
        assert cfg.build.dns == "8.8.8.8"
        assert cfg.build.python_optimize is False
        assert cfg.build.memory_preflight is False
        assert cfg.build.node_source == "build"


class TestValidateGlobalConfig:
    def test_valid_config(self, tmp_path: Path):
        repo_root = Path(__file__).resolve().parent.parent.parent
        target_dir = tmp_path / ".config" / "pi-container"
        target_file = ensure_global_config(config_dir=target_dir, repo_root=repo_root)

        is_valid, errors, version = validate_global_config(target_file, repo_root=repo_root)
        assert is_valid is True
        assert errors == []
        assert version == "0.6.6"

    def test_missing_file(self, tmp_path: Path):
        is_valid, errors, version = validate_global_config(tmp_path / "nonexistent.yaml")
        assert is_valid is False
        assert any("not found" in e for e in errors)
        assert version is None

    def test_invalid_yaml(self, tmp_path: Path):
        f = tmp_path / "bad.yaml"
        f.write_text("invalid: [unclosed")
        is_valid, errors, version = validate_global_config(f)
        assert is_valid is False
        assert any("not valid YAML" in e for e in errors)

    def test_non_dict_yaml(self, tmp_path: Path):
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        is_valid, errors, version = validate_global_config(f)
        assert is_valid is False
        assert any("must be a YAML mapping" in e for e in errors)

    def test_duplicate_keys(self, tmp_path: Path):
        f = tmp_path / "dup.yaml"
        f.write_text("schema_version: '0.6.6'\nschema_version: '0.6.6'\n")
        is_valid, errors, version = validate_global_config(f)
        assert is_valid is False
        assert any("duplicate key" in e for e in errors)

    def test_missing_schema_version(self, tmp_path: Path):
        f = tmp_path / "no_ver.yaml"
        f.write_text("runtime:\n  log_level: INFO\n")
        is_valid, errors, version = validate_global_config(f)
        assert is_valid is False
        assert any("schema_version: required field missing" in e for e in errors)

    def test_schema_version_mismatch(self, tmp_path: Path):
        repo_root = Path(__file__).resolve().parent.parent.parent
        f = tmp_path / "mismatch.yaml"
        f.write_text(
            yaml.dump(
                {
                    "schema_version": "9.9.9",
                    "runtime": {"log_level": "INFO", "proxy_upstream_network": "podman"},
                    "llama": {"build": {"repo": "a", "tag": "b", "backend": "cpu", "minimal": True, "cmake_flags": []}},
                    "build": {
                        "images": {"agent": "a", "proxy": "p", "builder": "b"},
                        "dns": "1.1.1.1",
                        "python_optimize": True,
                        "memory_preflight": True,
                        "node_source": "prebuilt",
                    },
                }
            )
        )
        with patch("config_schema.get_app_version", return_value="0.6.6"):
            is_valid, errors, version = validate_global_config(f, repo_root=repo_root)
            assert is_valid is False
            assert any(SCHEMA_VERSION_MISMATCH in e for e in errors)
