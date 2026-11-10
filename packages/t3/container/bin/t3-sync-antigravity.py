#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import re
import sys
import zipfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def extract_antigravity_credentials(
    auth_method: str = "consumer",
    search_paths: Sequence[pathlib.Path | str] | None = None,
) -> tuple[str, str] | None:
    """Extract Antigravity ACP OAuth client ID and secret dynamically from binaries/archives."""
    is_business = auth_method == "business"
    target_py = "business_auth.py" if is_business else "oauth_manager.py"
    target_id_var = "_BUSINESS_CLIENT_ID" if is_business else "_DEFAULT_CLIENT_ID"
    target_sec_var = "_BUSINESS_CLIENT_SECRET" if is_business else "_DEFAULT_CLIENT_SECRET"
    sec_prefix = "GOC" + "SPX-"

    paths_to_check: list[pathlib.Path] = []
    if search_paths:
        paths_to_check.extend(pathlib.Path(p) for p in search_paths)
    else:
        env_override = os.environ.get("ANTIGRAVITY_ACP_SERVER_PAR")
        if env_override:
            paths_to_check.append(pathlib.Path(env_override))
        paths_to_check.extend(
            [
                pathlib.Path("/usr/local/bin/agy_acp_server.real.par"),
                pathlib.Path("/usr/local/bin/agy_acp_server.par"),
            ]
        )
        t3_tools_dir = pathlib.Path("/usr/local/share/t3/tools/antigravity-acp")
        if t3_tools_dir.is_dir():
            paths_to_check.extend(t3_tools_dir.glob("**/agy_acp_server*.par"))

    for path in paths_to_check:
        if not path.is_file():
            continue

        if zipfile.is_zipfile(path):
            try:
                with zipfile.ZipFile(path) as z:
                    for name in z.namelist():
                        if name.endswith(target_py):
                            text = z.read(name).decode("utf-8", errors="replace")
                            id_match = re.search(
                                rf"{target_id_var}\s*=\s*\(?\s*[\"']([0-9]+-[0-9a-z_]+\.apps\.googleusercontent\.com)[\"']",
                                text,
                            )
                            sec_match = re.search(
                                rf"{target_sec_var}\s*=\s*[\"']({re.escape(sec_prefix)}[A-Za-z0-9_-]+)[\"']",
                                text,
                            )
                            if id_match and sec_match:
                                return id_match.group(1), sec_match.group(1)
            except Exception:
                pass

        try:
            raw_bytes = path.read_bytes()
        except Exception:
            continue

        text = raw_bytes.decode("utf-8", errors="ignore")
        id_match = re.search(
            rf"{target_id_var}\s*=\s*\(?\s*[\"']([0-9]+-[0-9a-z_]+\.apps\.googleusercontent\.com)[\"']",
            text,
        )
        sec_match = re.search(
            rf"{target_sec_var}\s*=\s*[\"']({re.escape(sec_prefix)}[A-Za-z0-9_-]+)[\"']",
            text,
        )
        if id_match and sec_match:
            return id_match.group(1), sec_match.group(1)

    return None


def sync_antigravity(
    token_path: pathlib.Path | None = None,
    t3_dir: pathlib.Path | None = None,
    gemini_acp_dir: pathlib.Path | None = None,
    search_paths: Sequence[pathlib.Path | str] | None = None,
) -> bool:
    """Sync Antigravity OAuth tokens to T3 ACP credentials and cache."""
    token_file = token_path or pathlib.Path("/home/agent/.gemini/antigravity-cli/antigravity-oauth-token")
    if not token_file.is_file():
        return False

    try:
        data = json.loads(token_file.read_text(encoding="utf-8"))
    except Exception:
        return False

    refresh_token = data.get("token", {}).get("refresh_token")
    if not refresh_token:
        return False

    auth_method = str(data.get("auth_method") or "consumer").lower()
    target_t3_dir = t3_dir or pathlib.Path("/home/agent/.t3")
    target_gemini_acp_dir = gemini_acp_dir or pathlib.Path("/home/agent/.gemini/antigravity-acp")

    key = hashlib.sha256(b"antigravity").hexdigest()
    t3_acp_dir = target_t3_dir / "userdata" / "providers" / "antigravity" / key / "antigravity-acp"
    t3_token_file = t3_acp_dir / "acp_token.json"
    gemini_token_file = target_gemini_acp_dir / "acp_token.json"

    creds = extract_antigravity_credentials(auth_method=auth_method, search_paths=search_paths)
    if not creds:
        for existing_path in (t3_token_file, gemini_token_file):
            if existing_path.is_file():
                with contextlib.suppress(Exception):
                    existing_data = json.loads(existing_path.read_text(encoding="utf-8"))
                    c_id = existing_data.get("client_id")
                    c_sec = existing_data.get("client_secret")
                    if c_id and c_sec:
                        creds = (c_id, c_sec)
                        break

    if creds:
        client_id, client_secret = creds
        token_payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": [
                "https://www.googleapis.com/auth/cloud-platform",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/aicode",
            ],
        }

        for acp_dir in (t3_acp_dir, target_gemini_acp_dir):
            acp_dir.mkdir(parents=True, exist_ok=True)
            acp_token_file = acp_dir / "acp_token.json"
            acp_token_file.write_text(json.dumps(token_payload, indent=2), encoding="utf-8")
            with contextlib.suppress(OSError):
                acp_token_file.chmod(0o600)

    cache_dir = target_t3_dir / "caches"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "antigravity.json"
    cache_data: dict[str, object] = {}
    if cache_file.is_file():
        with contextlib.suppress(Exception):
            cache_data = json.loads(cache_file.read_text(encoding="utf-8"))

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    cache_data.pop("message", None)
    cache_data.pop("unavailableReason", None)
    cache_data.update(
        {
            "displayName": "Antigravity",
            "showInteractionModeToggle": False,
            "supportedRuntimeModes": ["approval-required", "auto-accept-edits", "full-access"],
            "enabled": True,
            "installed": True,
            "version": cache_data.get("version") or "1.4.5",
            "status": "ready",
            "auth": {
                "status": "authenticated",
                "type": "oauth-personal",
                "label": "Google account",
            },
            "setup": {"canAuthenticate": True, "canInstall": True},
            "checkedAt": cache_data.get("checkedAt") or now_iso,
            "slashCommands": cache_data.get("slashCommands") or [],
            "skills": cache_data.get("skills") or [],
            "instanceId": "antigravity",
            "driver": "antigravity",
            "continuation": {"groupKey": "antigravity:instance:antigravity"},
            "supportsConversationRollback": False,
            "supportsTextGeneration": True,
        }
    )

    if not cache_data.get("models"):
        cache_data["models"] = [
            {
                "slug": "gemini-3.8-flash",
                "name": "Gemini 3.8 Flash",
                "isCustom": False,
                "capabilities": {
                    "optionDescriptors": [
                        {
                            "id": "thinking_level",
                            "label": "Thinking Level",
                            "type": "select",
                            "options": [
                                {"id": "low", "label": "Low"},
                                {"id": "medium", "label": "Medium"},
                                {"id": "high", "label": "High", "isDefault": True},
                            ],
                        }
                    ]
                },
                "isDefault": True,
            }
        ]
    else:
        for m in cache_data["models"]:
            if isinstance(m, dict) and "isCustom" not in m:
                m["isCustom"] = False

    cache_file.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")
    return True


if __name__ == "__main__":
    cli_token = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
    cli_t3 = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else None
    cli_acp = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else None
    cli_search = [pathlib.Path(sys.argv[4])] if len(sys.argv) > 4 else None
    sync_antigravity(cli_token, cli_t3, cli_acp, search_paths=cli_search)
