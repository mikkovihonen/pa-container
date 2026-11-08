from __future__ import annotations

import pytest

from agents.synthesis import (
    extract_models_from_yaml,
    load_project_models,
    resolve_models_file,
)
from config_schema import validate_models


def test_resolve_models_file(tmp_path):
    pa_dir = tmp_path / ".pa-container"
    pa_dir.mkdir()
    assert resolve_models_file(pa_dir) is None

    # models.yaml
    yaml_path = pa_dir / "models.yaml"
    yaml_path.write_text("allow: []")
    assert resolve_models_file(pa_dir) == yaml_path

    yaml_path.unlink()
    # models.yml is NOT supported
    yml_path = pa_dir / "models.yml"
    yml_path.write_text("allow: []")
    assert resolve_models_file(pa_dir) is None


def test_extract_models_from_yaml_with_registries(tmp_path):
    models_dir = tmp_path / "models"
    gateways_dir = tmp_path / "gateways"
    models_dir.mkdir()
    gateways_dir.mkdir()

    # Seed model definition
    (models_dir / "test-model.yaml").write_text(
        "id: test-model\n"
        "kind: llama-server\n"
        "flags: []\n"
        "hfModels:\n"
        "  main:\n"
        "    fileFlag: --model\n"
        "    repo: org/repo\n"
        "    file: model.gguf\n"
    )

    # Seed gateway definition
    (gateways_dir / "test-gw.yaml").write_text(
        "id: test-gw\nbaseUrl: https://api.gateway.example\ntype: openai-compat\n"
    )

    data = {
        "default": "test-model",
        "allow": [
            "test-model",
            "test-gw",
            {"id": "test-model", "provider": "custom-alias", "baseUrl": "http://llama:8888/v1"},
        ],
    }

    synthetic, servers, hostnames, gateways, default_model = extract_models_from_yaml(
        data, models_dir=models_dir, gateways_dir=gateways_dir
    )

    assert default_model == "test-model"
    assert len(servers) == 2  # test-model and custom-alias
    assert servers[0]["name"] == "test-model"
    assert servers[0]["baseUrl"] == "http://llama:9999/v1"
    assert servers[1]["name"] == "custom-alias"
    assert servers[1]["baseUrl"] == "http://llama:8888/v1"

    assert len(gateways) == 1
    assert gateways[0]["name"] == "test-gw"
    assert gateways[0]["baseUrl"] == "https://api.gateway.example"

    assert "llama" in hostnames
    assert "api.gateway.example" in hostnames

    # Unknown model in allowlist raises ValueError
    bad_data = {"allow": ["unknown-model"]}
    with pytest.raises(ValueError, match="Model or gateway 'unknown-model' listed in models.yaml allowlist not found"):
        extract_models_from_yaml(bad_data, models_dir=models_dir, gateways_dir=gateways_dir)


def test_load_project_models_yaml(tmp_path):
    pa_dir = tmp_path / ".pa-container"
    pa_dir.mkdir()
    gateways_dir = tmp_path / "gateways"
    gateways_dir.mkdir()
    (gateways_dir / "my-gw.yaml").write_text("id: my-gw\nbaseUrl: https://api.mygw.com\n")

    yaml_file = pa_dir / "models.yaml"
    yaml_file.write_text("default: my-gw\nallow:\n  - my-gw\n")

    synthetic, servers, hostnames, gateways, default_m, resolved = load_project_models(
        pa_dir, gateways_dir=gateways_dir
    )
    assert resolved == yaml_file
    assert default_m == "my-gw"
    assert len(gateways) == 1
    assert gateways[0]["name"] == "my-gw"


def test_load_project_models_missing(tmp_path):
    pa_dir = tmp_path / ".pa-container"
    pa_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="No models configuration found"):
        load_project_models(pa_dir)


def test_validate_models_yaml(tmp_path):
    yaml_file = tmp_path / "models.yaml"

    # Valid
    yaml_file.write_text("default: model1\nallow:\n  - model1\n  - id: model2\n")
    is_valid, errors = validate_models(yaml_file)
    assert is_valid is True
    assert errors == []

    # Missing allow
    yaml_file.write_text("default: model1\n")
    is_valid, errors = validate_models(yaml_file)
    assert is_valid is False
    assert any("allow: required field missing" in e for e in errors)

    # Empty allow list
    yaml_file.write_text("allow: []\n")
    is_valid, errors = validate_models(yaml_file)
    assert is_valid is False
    assert any("allow: list must not be empty" in e for e in errors)

    # Empty string inside allow
    yaml_file.write_text("allow:\n  - ''\n")
    is_valid, errors = validate_models(yaml_file)
    assert is_valid is False
    assert any("item must not be empty string" in e for e in errors)
