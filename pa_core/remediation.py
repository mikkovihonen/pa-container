from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from registry import GatewayDef


@dataclass(frozen=True)
class RemediationAction:
    """Actionable remediation guidance with an optional code snippet and commands."""

    description: str
    snippet: str | None = None
    snippet_lang: str = "yaml"
    companion_commands: Sequence[str] = field(default_factory=tuple)

    def to_plain_text(self) -> str:
        """Render a plain-text fallback representation."""
        lines = [self.description]
        if self.snippet:
            lines.append("")
            for s_line in self.snippet.splitlines():
                lines.append(f"    {s_line}")
        if self.companion_commands:
            lines.append("")
            lines.append("  Credential setup command:")
            for cmd in self.companion_commands:
                lines.append(f"    $ {cmd}")
        return "\n".join(lines)

    def __str__(self) -> str:
        res = self.description
        if self.companion_commands:
            res += f" ({'; '.join(self.companion_commands)})"
        return res


def infer_container_env_var(gw_def: GatewayDef) -> str:
    """Infer the canonical container environment variable name for a gateway."""
    for tr in gw_def.token_replacer:
        patterns = tr.get("content_patterns") or []
        for pat in patterns:
            regex_str = pat.get("regex", "")
            m = re.search(r"([A-Za-z0-9_]+)_PLACEHOLDER", regex_str)
            if m:
                return m.group(1)

    clean_id = re.sub(r"[^A-Za-z0-9_]", "_", gw_def.id.upper())
    if gw_def.auth and gw_def.auth.type == "openid":
        return f"{clean_id}_TOKEN"
    return f"{clean_id}_API_KEY"


def synthesize_gateway_allow_item(
    model_id: str,
    gw_def: GatewayDef | None = None,
    existing_item: Any = None,
    config_path: Path | None = None,
    gateways_dir: Path | None = None,
) -> RemediationAction:
    """Generate a canonical, valid allow item for an external gateway."""
    if gw_def is None:
        from registry import load_gateway_def

        gw_def = load_gateway_def(model_id, registry_dir=gateways_dir)

    file_label = f" in {config_path.name}" if config_path else ""

    if gw_def is None:
        clean_id = re.sub(r"[^A-Za-z0-9_]", "_", model_id.upper())
        snippet = (
            f"- id: {model_id}\n"
            f"  provider: {model_id}\n"
            f"  containerEnvVar: {clean_id}_API_KEY\n"
            f"  keyringService: pa-container\n"
            f"  keyringAccount: {clean_id}_API_KEY"
        )
        return RemediationAction(
            description=f"Configure item '{model_id}' under 'allow:'{file_label} as a mapping:",
            snippet=snippet,
            snippet_lang="yaml",
            companion_commands=(f"uv run keyring set pa-container {clean_id}_API_KEY",),
        )

    existing_dict = existing_item if isinstance(existing_item, dict) else {}
    provider = existing_dict.get("provider") or model_id

    models_snippet = ""
    if existing_dict.get("models"):
        models_snippet = "\n  models:\n" + "\n".join(
            f"    - {m if isinstance(m, str) else m.get('id', '')}" for m in existing_dict["models"]
        )
    elif model_id == "opper":
        models_snippet = "\n  models:\n    - glm-5.3\n    - claude-sonnet-4-6"
    else:
        models_snippet = f"\n  models:\n    - <{model_id}-model-id>"

    if gw_def.auth and gw_def.auth.type == "api-key":
        env_var = existing_dict.get("containerEnvVar") or infer_container_env_var(gw_def)
        keyring_service = existing_dict.get("keyringService") or "pa-container"
        keyring_account = existing_dict.get("keyringAccount") or env_var

        snippet = (
            f"- id: {model_id}\n"
            f"  provider: {provider}\n"
            f"  containerEnvVar: {env_var}\n"
            f"  keyringService: {keyring_service}\n"
            f"  keyringAccount: {keyring_account}"
            f"{models_snippet}"
        )
        return RemediationAction(
            description=f"Replace '{model_id}' under 'allow:'{file_label} with:",
            snippet=snippet,
            snippet_lang="yaml",
            companion_commands=(f"uv run keyring set {keyring_service} {keyring_account}",),
        )

    if gw_def.auth and gw_def.auth.type == "openid":
        env_var = existing_dict.get("containerEnvVar") or infer_container_env_var(gw_def)
        snippet = f"- id: {model_id}\n  provider: {provider}\n  containerEnvVar: {env_var}{models_snippet}"
        return RemediationAction(
            description=f"Configure '{model_id}' under 'allow:'{file_label} with containerEnvVar:",
            snippet=snippet,
            snippet_lang="yaml",
            companion_commands=(),
        )

    return RemediationAction(
        description=f"Add '{model_id}' under 'allow:'{file_label}:",
        snippet=f"- {model_id}",
        snippet_lang="yaml",
        companion_commands=(),
    )


def get_models_remediations(
    models_path: Path,
    gateways_dir: Path | None = None,
) -> list[RemediationAction]:
    """Inspect models.yaml and generate actionable remediations for any validation errors."""
    remediations: list[RemediationAction] = []
    if not models_path.exists():
        remediations.append(
            RemediationAction(
                description=f"Create {models_path.name} with standard allowlist:",
                snippet=(
                    "# Default active model for this workspace\n"
                    "default: Qwen3.6-35B-A3B-UD-Q6_K_XL\n\n"
                    "# Allowlist of models and gateways enabled for this project\n"
                    "allow:\n"
                    "  - Qwen3.6-35B-A3B-UD-Q6_K_XL\n"
                ),
                snippet_lang="yaml",
            )
        )
        return remediations

    try:
        from yaml_strict import load_yaml_strict

        data = load_yaml_strict(models_path.read_text())
    except Exception:
        # YAML syntax error, no structured remediation
        return remediations

    if not isinstance(data, dict):
        return remediations

    allow = data.get("allow")
    if allow is None:
        remediations.append(
            RemediationAction(
                description=f"Add the required 'allow:' list to {models_path.name}:",
                snippet="allow:\n  - Qwen3.6-35B-A3B-UD-Q6_K_XL\n",
                snippet_lang="yaml",
            )
        )
        return remediations

    if not isinstance(allow, list):
        return remediations

    from registry import load_gateway_def

    for item in allow:
        gw_def = None
        model_id = ""
        is_invalid = False

        if isinstance(item, str):
            model_id = item.strip()
            if not model_id:
                continue
            gw_def = load_gateway_def(model_id, registry_dir=gateways_dir)
            if gw_def is not None and gw_def.auth is not None and gw_def.auth.type in ("api-key", "openid"):
                is_invalid = True
        elif isinstance(item, dict):
            m_id = item.get("id")
            if not m_id or not isinstance(m_id, str):
                continue
            model_id = m_id.strip()
            gw_def = load_gateway_def(model_id, registry_dir=gateways_dir)
            if gw_def is not None and gw_def.auth is not None:
                if gw_def.auth.type == "api-key":
                    for req_field in ("containerEnvVar", "keyringService", "keyringAccount"):
                        val = item.get(req_field)
                        if not val or not isinstance(val, str) or not val.strip():
                            is_invalid = True
                            break
                elif gw_def.auth.type == "openid":
                    val = item.get("containerEnvVar")
                    if not val or not isinstance(val, str) or not val.strip():
                        is_invalid = True

        if is_invalid and model_id:
            action = synthesize_gateway_allow_item(
                model_id=model_id,
                gw_def=gw_def,
                existing_item=item,
                config_path=models_path,
                gateways_dir=gateways_dir,
            )
            remediations.append(action)

    return remediations
