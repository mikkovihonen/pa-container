import sys

sys.dont_write_bytecode = True

"""Tests for src/registry.py (global model & gateway registry loader)."""

from pathlib import Path

from registry import (
    GatewayDef,
    LlamaServerModelDef,
    list_gateway_defs,
    list_model_defs,
    load_gateway_def,
    load_model_def,
    seed_default_chat_templates,
    seed_default_gateways,
    seed_default_models,
)


def test_seed_default_models(tmp_path: Path):
    reg_dir = tmp_path / "models"
    assert not reg_dir.exists()

    seeded = seed_default_models(reg_dir)
    assert len(seeded) == 1
    assert seeded[0] == "Qwen3.6-35B-A3B-UD-Q6_K_XL.yaml"
    assert (reg_dir / "Qwen3.6-35B-A3B-UD-Q6_K_XL.yaml").exists()
    assert (tmp_path / "chat-templates" / "Qwen3.6-35B-A3B-UD-Q6_K-XL" / "chat_template.jinja").exists()

    # Second call does not re-seed or overwrite
    seeded_again = seed_default_models(reg_dir)
    assert seeded_again == []


def test_seed_default_chat_templates(tmp_path: Path):
    tpl_dir = tmp_path / "custom_chat_templates"
    assert not tpl_dir.exists()

    seeded = seed_default_chat_templates(tpl_dir)
    assert len(seeded) == 1
    assert (tpl_dir / "Qwen3.6-35B-A3B-UD-Q6_K-XL" / "chat_template.jinja").exists()

    # Second call is idempotent
    seeded_again = seed_default_chat_templates(tpl_dir)
    assert seeded_again == []


def test_load_llama_server_model_def(tmp_path: Path):
    reg_dir = tmp_path / "models"
    seed_default_models(reg_dir)

    m_def = load_model_def("Qwen3.6-35B-A3B-UD-Q6_K_XL", reg_dir)
    assert m_def is not None
    assert isinstance(m_def, LlamaServerModelDef)
    assert m_def.id == "Qwen3.6-35B-A3B-UD-Q6_K_XL"
    assert "main" in m_def.server_config.hf_models
    assert m_def.server_config.hf_models["main"].repo == "unsloth/Qwen3.6-35B-A3B-MTP-GGUF"
    assert "--load-mode" in m_def.server_config.flags


def test_load_gateway_def_oidc_discovery(tmp_path: Path):
    gw_dir = tmp_path / "gateways"
    gw_dir.mkdir(parents=True)

    gw_yaml = """
id: corp
description: "Corporate Gateway"
type: corp
baseUrl: "https://gw.example.com/v1"
auth:
  type: openid
  discoveryUrl: "https://auth.example.com/.well-known/openid-configuration"
  clientId: "pa-container"
  scopes:
    - "openid"
    - "profile"
"""
    (gw_dir / "corp.yaml").write_text(gw_yaml)

    gw_def = load_gateway_def("corp", gw_dir)
    assert gw_def is not None
    assert isinstance(gw_def, GatewayDef)
    assert gw_def.id == "corp"
    assert gw_def.base_url == "https://gw.example.com/v1"
    assert gw_def.auth is not None
    assert gw_def.auth.type == "openid"
    assert gw_def.auth.discovery_url == "https://auth.example.com/.well-known/openid-configuration"
    assert gw_def.auth.client_id == "pa-container"
    assert "openid" in gw_def.auth.scopes


def test_load_gateway_def_explicit_endpoints(tmp_path: Path):
    gw_dir = tmp_path / "gateways"
    gw_dir.mkdir(parents=True)

    gw_yaml = """
id: custom-gw
type: generic-openai
baseUrl: "https://api.gateway.example.com/v1"
auth:
  type: openid
  authorizationUrl: "https://auth.example.com/oauth/authorize"
  tokenUrl: "https://auth.example.com/oauth/token"
  clientId: "test-client"
  tokenCache: "~/.cache/pa-container/tokens/custom.json"
"""
    (gw_dir / "custom-gw.yaml").write_text(gw_yaml)

    gw_def = load_gateway_def("custom-gw", gw_dir)
    assert gw_def is not None
    assert isinstance(gw_def, GatewayDef)
    assert gw_def.auth is not None
    assert gw_def.auth.authorization_url == "https://auth.example.com/oauth/authorize"
    assert gw_def.auth.token_url == "https://auth.example.com/oauth/token"
    assert gw_def.auth.token_cache == Path.home() / ".cache" / "pa-container" / "tokens" / "custom.json"


def test_load_gateway_def_api_key(tmp_path: Path):
    gw_dir = tmp_path / "gateways"
    gw_dir.mkdir(parents=True)

    gw_yaml = """
id: opper
description: "Opper AI Gateway"
type: openai-compat
baseUrl: "https://api.opper.ai/v3/compat"
auth:
  type: api-key
allowlist:
  - name: "opper-allow"
    mode: "allow"
    hostnames: ["api.opper.ai"]
token_replacer:
  - name: "Inject Opper Key"
    hostnames: ["api.opper.ai"]
"""
    (gw_dir / "opper.yaml").write_text(gw_yaml)

    gw_def = load_gateway_def("opper", gw_dir)
    assert gw_def is not None
    assert isinstance(gw_def, GatewayDef)
    assert gw_def.id == "opper"
    assert gw_def.gateway_type == "openai-compat"
    assert gw_def.base_url == "https://api.opper.ai/v3/compat"
    assert gw_def.auth is not None
    assert gw_def.auth.type == "api-key"
    assert len(gw_def.allowlist) == 1
    assert gw_def.allowlist[0]["name"] == "opper-allow"
    assert len(gw_def.token_replacer) == 1
    assert gw_def.token_replacer[0]["name"] == "Inject Opper Key"


def test_load_gateway_def_defaults_to_openai_compat(tmp_path: Path):
    gw_dir = tmp_path / "gateways"
    gw_dir.mkdir(parents=True)

    gw_yaml = """
id: generic-gw
baseUrl: "https://api.example.com/v1"
"""
    (gw_dir / "generic-gw.yaml").write_text(gw_yaml)

    gw_def = load_gateway_def("generic-gw", gw_dir)
    assert gw_def is not None
    assert isinstance(gw_def, GatewayDef)
    assert gw_def.gateway_type == "openai-compat"


def test_load_nonexistent_model_returns_none(tmp_path: Path):
    reg_dir = tmp_path / "models"
    reg_dir.mkdir(parents=True)
    assert load_model_def("does-not-exist", reg_dir) is None


def test_load_nonexistent_gateway_returns_none(tmp_path: Path):
    gw_dir = tmp_path / "gateways"
    gw_dir.mkdir(parents=True)
    assert load_gateway_def("does-not-exist", gw_dir) is None


def test_load_corrupt_file_returns_none(tmp_path: Path):
    reg_dir = tmp_path / "models"
    reg_dir.mkdir(parents=True)
    (reg_dir / "broken.yaml").write_text("invalid: yaml: [unclosed")
    assert load_model_def("broken", reg_dir) is None

    gw_dir = tmp_path / "gateways"
    gw_dir.mkdir(parents=True)
    (gw_dir / "broken.yaml").write_text("invalid: yaml: [unclosed")
    assert load_gateway_def("broken", gw_dir) is None


def test_list_model_defs(tmp_path: Path):
    reg_dir = tmp_path / "models"
    seed_default_models(reg_dir)

    defs = list_model_defs(reg_dir)
    assert len(defs) == 1
    assert defs[0].id == "Qwen3.6-35B-A3B-UD-Q6_K_XL"


def test_list_gateway_defs(tmp_path: Path):
    gw_dir = tmp_path / "gateways"
    gw_dir.mkdir(parents=True)

    gw_yaml = """
id: opper
baseUrl: "https://api.opper.ai/v3/compat"
"""
    (gw_dir / "opper.yaml").write_text(gw_yaml)

    defs = list_gateway_defs(gw_dir)
    assert len(defs) == 1
    assert defs[0].id == "opper"


def test_list_defs_strictly_yaml(tmp_path: Path):
    gw_dir = tmp_path / "gateways"
    gw_dir.mkdir(parents=True)
    (gw_dir / "valid.yaml").write_text("id: valid\nbaseUrl: https://api.example.com\n")
    (gw_dir / "ignored.yml").write_text("id: ignored\nbaseUrl: https://api.example.com\n")
    (gw_dir / "ignored.json").write_text('{"id": "ignored", "baseUrl": "https://api.example.com"}')

    defs = list_gateway_defs(gw_dir)
    assert len(defs) == 1
    assert defs[0].id == "valid"


def test_seed_default_gateways(tmp_path: Path):
    gw_dir = tmp_path / "gateways"
    assert not gw_dir.exists()

    seeded = seed_default_gateways(gw_dir)
    assert len(seeded) == 9
    expected = {
        "anthropic.yaml",
        "anthropic-account.yaml",
        "deepseek.yaml",
        "gemini.yaml",
        "google-account.yaml",
        "groq.yaml",
        "openai.yaml",
        "openrouter.yaml",
        "opper.yaml",
    }
    assert set(seeded) == expected
    for name in expected:
        assert (gw_dir / name).exists()

    # Second call does not re-seed
    seeded_again = seed_default_gateways(gw_dir)
    assert seeded_again == []


def test_all_bundled_gateways_valid():
    """Verify all 9 bundled gateways load properly with self-contained allowlist and token_replacer."""
    from registry import BUNDLED_GATEWAYS_DIR

    expected_ids = {
        "anthropic",
        "anthropic-account",
        "deepseek",
        "gemini",
        "google-account",
        "groq",
        "openai",
        "openrouter",
        "opper",
    }
    defs = list_gateway_defs(BUNDLED_GATEWAYS_DIR)
    loaded_ids = {d.id for d in defs}
    assert loaded_ids == expected_ids

    for d in defs:
        assert d.base_url.startswith("https://")
        assert d.auth is not None
        assert d.auth.type in ("api-key", "agent-native")
        assert len(d.allowlist) >= 1
        if d.auth.type == "api-key":
            assert len(d.token_replacer) >= 1
        elif d.auth.type == "agent-native":
            assert len(d.token_replacer) == 0
        # No credentials in global definitions
        assert not hasattr(d.auth, "env_var") or getattr(d.auth, "env_var", None) is None


def test_empty_or_commented_gateway_yaml_rejected(tmp_path: Path):
    """Empty or completely commented out YAML files are rejected as invalid."""
    gw_dir = tmp_path / "gateways"
    gw_dir.mkdir(parents=True)
    (gw_dir / "empty.yaml").write_text("# Only comments\n# nothing else\n")

    gw_def = load_gateway_def("empty", gw_dir)
    assert gw_def is None
