from __future__ import annotations

from typing import TYPE_CHECKING

from registry import GatewayAuth, GatewayDef
from remediation import (
    RemediationAction,
    get_models_remediations,
    infer_container_env_var,
    synthesize_gateway_allow_item,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_remediation_action_methods() -> None:
    action = RemediationAction(
        description="Replace entry in models.yaml with:",
        snippet="- id: opper\n  provider: opper",
        snippet_lang="yaml",
        companion_commands=("uv run keyring set pa-container OPPER_API_KEY",),
    )
    plain = action.to_plain_text()
    assert "Replace entry in models.yaml with:" in plain
    assert "    - id: opper" in plain
    assert "uv run keyring set pa-container OPPER_API_KEY" in plain
    assert "uv run keyring set" in str(action)


def test_infer_container_env_var() -> None:
    gw_def = GatewayDef(
        id="test-gw",
        base_url="https://api.test.ai",
        token_replacer=[
            {
                "content_patterns": [
                    {"regex": r"(?<=Bearer\s)TEST_AI_KEY_PLACEHOLDER"},
                ]
            }
        ],
    )
    assert infer_container_env_var(gw_def) == "TEST_AI_KEY"

    fallback_gw = GatewayDef(id="custom-gw", base_url="https://api.custom.ai")
    assert infer_container_env_var(fallback_gw) == "CUSTOM_GW_API_KEY"

    openid_gw = GatewayDef(
        id="sso-gw",
        base_url="https://api.sso.ai",
        auth=GatewayAuth(type="openid"),
    )
    assert infer_container_env_var(openid_gw) == "SSO_GW_TOKEN"


def test_synthesize_gateway_allow_item_api_key(tmp_path: Path) -> None:
    gw_def = GatewayDef(
        id="opper",
        base_url="https://api.opper.ai/v3/compat",
        auth=GatewayAuth(type="api-key"),
        token_replacer=[
            {
                "content_patterns": [
                    {"regex": r"(?<=Bearer\s)OPPER_API_KEY_PLACEHOLDER"},
                ]
            }
        ],
    )
    config_file = tmp_path / "models.yaml"
    action = synthesize_gateway_allow_item("opper", gw_def=gw_def, config_path=config_file)
    assert "Replace 'opper' under 'allow:' in models.yaml with:" in action.description
    assert action.snippet is not None
    assert "- id: opper" in action.snippet
    assert "containerEnvVar: OPPER_API_KEY" in action.snippet
    assert "keyringService: pa-container" in action.snippet
    assert "keyringAccount: OPPER_API_KEY" in action.snippet
    assert "models:" in action.snippet
    assert "- glm-5.3" in action.snippet
    assert action.companion_commands == ("uv run keyring set pa-container OPPER_API_KEY",)


def test_synthesize_gateway_allow_item_partial_dict(tmp_path: Path) -> None:
    gw_def = GatewayDef(
        id="opper",
        base_url="https://api.opper.ai/v3/compat",
        auth=GatewayAuth(type="api-key"),
    )
    existing = {"id": "opper", "containerEnvVar": "CUSTOM_ENV_KEY"}
    action = synthesize_gateway_allow_item("opper", gw_def=gw_def, existing_item=existing)
    assert action.snippet is not None
    assert "containerEnvVar: CUSTOM_ENV_KEY" in action.snippet
    assert "keyringAccount: CUSTOM_ENV_KEY" in action.snippet
    assert action.companion_commands == ("uv run keyring set pa-container CUSTOM_ENV_KEY",)


def test_get_models_remediations_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "models.yaml"
    rems = get_models_remediations(missing)
    assert len(rems) == 1
    assert "Create models.yaml" in rems[0].description
    assert "default: Qwen3.6-35B-A3B-UD-Q6_K_XL" in (rems[0].snippet or "")


def test_get_models_remediations_for_bare_gateway(tmp_path: Path) -> None:
    models_file = tmp_path / "models.yaml"
    models_file.write_text("allow:\n  - opper\n")

    gw_dir = tmp_path / "gateways"
    gw_dir.mkdir()
    (gw_dir / "opper.yaml").write_text(
        "id: opper\n"
        "baseUrl: https://api.opper.ai\n"
        "auth:\n"
        "  type: api-key\n"
        "token_replacer:\n"
        "  - content_patterns:\n"
        "      - regex: '(?<=Bearer )OPPER_API_KEY_PLACEHOLDER'\n"
    )

    rems = get_models_remediations(models_file, gateways_dir=gw_dir)
    assert len(rems) == 1
    assert "- id: opper" in (rems[0].snippet or "")
    assert "containerEnvVar: OPPER_API_KEY" in (rems[0].snippet or "")
    assert rems[0].companion_commands == ("uv run keyring set pa-container OPPER_API_KEY",)
