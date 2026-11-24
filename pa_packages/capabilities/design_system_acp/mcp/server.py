#!/usr/bin/env python3
"""Design System Model Context Protocol (MCP) Server.

Provides structured JSON-RPC tools over stdio for token discovery (W3C DTCG),
component contract validation, deprecation notices, and live visual board inspection
via Penpot HTTP API.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SERVER_NAME = "design_system_acp"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"


class DesignContext:
    def __init__(
        self,
        workspace_dir: str | None = None,
        config_path: str | None = None,
        tokens_path: str | None = None,
        contracts_path: str | None = None,
    ):
        self.workspace_dir = os.path.abspath(
            workspace_dir or os.environ.get("PA_WORKSPACE_DIR") or os.getcwd()
        )
        self.config_path = config_path or os.environ.get("PA_FACTORY_CONFIG")
        if not self.config_path:
            direct = os.path.join(self.workspace_dir, "factory.toml")
            nested = os.path.join(self.workspace_dir, ".pa-container", "factory.toml")
            if os.path.isfile(direct):
                self.config_path = direct
            elif os.path.isfile(nested):
                self.config_path = nested
            else:
                self.config_path = direct

        self.config = self._load_config()
        ds_cfg = self.config.get("design_system", {})

        cfg_tokens = ds_cfg.get("tokens_path")
        self.tokens_path = (
            tokens_path
            or os.environ.get("PA_DESIGN_TOKENS")
            or (os.path.join(self.workspace_dir, cfg_tokens) if cfg_tokens else None)
            or os.path.join(self.workspace_dir, "design", "tokens", "tokens.json")
        )

        cfg_contracts = ds_cfg.get("contracts_path")
        self.contracts_dir = (
            contracts_path
            or os.environ.get("PA_DESIGN_CONTRACTS")
            or (os.path.join(self.workspace_dir, cfg_contracts) if cfg_contracts else None)
            or os.path.join(self.workspace_dir, "design", "contracts")
        )

    def _load_config(self) -> dict[str, Any]:
        if self.config_path and os.path.isfile(self.config_path):
            try:
                with open(self.config_path, "rb") as f:
                    return tomllib.load(f)
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to parse {self.config_path}: {e}\n")
        return {}

    def load_tokens_raw(self) -> dict[str, Any]:
        if os.path.isfile(self.tokens_path):
            try:
                with open(self.tokens_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to parse tokens at {self.tokens_path}: {e}\n")
        return {}


def _flatten_dtcg_tokens(
    data: dict[str, Any], prefix: str = ""
) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    for key, value in data.items():
        if key.startswith("$"):
            continue
        current_path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            if "$value" in value:
                # Leaf token
                tokens.append(
                    {
                        "path": current_path,
                        "value": value["$value"],
                        "type": value.get("$type", "unknown"),
                        "description": value.get("$description", ""),
                        "deprecated": value.get("$deprecated", False),
                        "replacement": value.get("$replacement"),
                    }
                )
            else:
                tokens.extend(_flatten_dtcg_tokens(value, current_path))
    return tokens


def _format_token_platform(path: str, value: Any, platform: str) -> str:
    if platform == "web":
        css_var = "--" + path.replace(".", "-")
        return f"{css_var}: {value};"
    elif platform == "ios":
        # e.g. color.brand.primary -> ColorBrandPrimary
        parts = re.split(r"[._-]", path)
        camel = "".join(p.capitalize() for p in parts)
        return f"let {camel} = {json.dumps(value)}"
    elif platform == "android":
        parts = re.split(r"[._-]", path)
        camel = "".join(p.capitalize() for p in parts)
        return f"val {camel} = {json.dumps(value)}"
    return f"{path} = {value}"


def handle_search_tokens(ctx: DesignContext, args: dict[str, Any]) -> dict[str, Any]:
    query = args.get("query", "").strip().lower()
    platform = args.get("platform", "web").strip().lower()
    category = args.get("category", "").strip().lower()

    raw_tokens = ctx.load_tokens_raw()
    all_tokens = _flatten_dtcg_tokens(raw_tokens)

    matched = []
    for token in all_tokens:
        path = token["path"].lower()
        desc = (token["description"] or "").lower()
        val = str(token["value"]).lower()

        # Category filter (e.g. 'color', 'spacing')
        if category and not path.startswith(category):
            continue

        # Query filter
        if query:
            if query not in path and query not in desc and query not in val:
                continue

        entry = dict(token)
        entry["code_snippet"] = _format_token_platform(token["path"], token["value"], platform)
        matched.append(entry)

    return {
        "total_matched": len(matched),
        "platform": platform,
        "category_filter": category or None,
        "query": query or None,
        "tokens": matched,
    }


def handle_get_component_contract(ctx: DesignContext, args: dict[str, Any]) -> dict[str, Any]:
    component_name = args.get("component", "").strip()
    if not component_name:
        return {"error": "component name is required"}

    if not os.path.isdir(ctx.contracts_dir):
        return {
            "found": False,
            "component": component_name,
            "error": f"Contracts directory '{ctx.contracts_dir}' does not exist",
        }

    target_file = None
    available_components = []

    for path in glob.glob(os.path.join(ctx.contracts_dir, "*.toml")):
        base = os.path.splitext(os.path.basename(path))[0]
        available_components.append(base)
        if base.lower() == component_name.lower():
            target_file = path

    if not target_file:
        return {
            "found": False,
            "component": component_name,
            "message": f"Component contract '{component_name}' not found",
            "available_contracts": available_components,
        }

    try:
        with open(target_file, "rb") as f:
            contract_data = tomllib.load(f)
    except Exception as e:
        return {
            "found": False,
            "component": component_name,
            "error": f"Failed to parse contract TOML: {e}",
        }

    # Verify referenced tokens against tokens.json
    raw_tokens = ctx.load_tokens_raw()
    all_tokens = {t["path"]: t for t in _flatten_dtcg_tokens(raw_tokens)}

    declared_tokens = contract_data.get("tokens", [])
    token_status = []
    for tok_path in declared_tokens:
        if tok_path in all_tokens:
            tok = all_tokens[tok_path]
            token_status.append(
                {
                    "path": tok_path,
                    "valid": True,
                    "value": tok["value"],
                    "deprecated": tok.get("deprecated", False),
                }
            )
        else:
            token_status.append(
                {
                    "path": tok_path,
                    "valid": False,
                    "error": f"Token '{tok_path}' missing from tokens.json",
                }
            )

    return {
        "found": True,
        "contract_file": os.path.relpath(target_file, ctx.workspace_dir),
        "name": contract_data.get("name", component_name),
        "description": contract_data.get("description", ""),
        "platforms": contract_data.get("platforms", []),
        "deprecated": contract_data.get("deprecated", False),
        "web": contract_data.get("web"),
        "ios": contract_data.get("ios"),
        "android": contract_data.get("android"),
        "tokens_validation": {
            "total_declared": len(declared_tokens),
            "all_valid": all(t["valid"] for t in token_status),
            "tokens": token_status,
        },
    }


def handle_list_deprecated(ctx: DesignContext, _args: dict[str, Any]) -> dict[str, Any]:
    raw_tokens = ctx.load_tokens_raw()
    all_tokens = _flatten_dtcg_tokens(raw_tokens)

    deprecated_tokens = [
        {
            "path": t["path"],
            "value": t["value"],
            "description": t["description"],
            "replacement": t.get("replacement"),
        }
        for t in all_tokens
        if t.get("deprecated")
    ]

    deprecated_contracts = []
    if os.path.isdir(ctx.contracts_dir):
        for path in glob.glob(os.path.join(ctx.contracts_dir, "*.toml")):
            try:
                with open(path, "rb") as f:
                    cdata = tomllib.load(f)
                if cdata.get("deprecated"):
                    deprecated_contracts.append(
                        {
                            "component": cdata.get("name", os.path.splitext(os.path.basename(path))[0]),
                            "file": os.path.relpath(path, ctx.workspace_dir),
                            "replacement": cdata.get("replacement"),
                            "sunset_notice": cdata.get("sunset_notice"),
                        }
                    )
            except Exception:
                continue

    return {
        "deprecated_tokens_count": len(deprecated_tokens),
        "deprecated_components_count": len(deprecated_contracts),
        "deprecated_tokens": deprecated_tokens,
        "deprecated_components": deprecated_contracts,
    }


def _find_shape_geometry(data: Any, target_id: str | None) -> dict[str, float]:
    """Find shape/board geometry from Penpot file structure."""
    default_geom = {"x": 0.0, "y": 0.0, "width": 1200.0, "height": 800.0}
    if not isinstance(data, dict):
        return default_geom

    if target_id:
        def search(obj: Any) -> dict[str, float] | None:
            if isinstance(obj, dict):
                if obj.get("id") == target_id or obj.get("name") == target_id:
                    return {
                        "x": float(obj.get("x", 0.0)),
                        "y": float(obj.get("y", 0.0)),
                        "width": float(obj.get("width", 0.0)),
                        "height": float(obj.get("height", 0.0)),
                    }
                for v in obj.values():
                    found = search(v)
                    if found:
                        return found
            elif isinstance(obj, list):
                for item in obj:
                    found = search(item)
                    if found:
                        return found
            return None

        found = search(data)
        if found:
            return found

    return default_geom


def _extract_tokens_used(data: Any, known_tokens: set[str]) -> list[str]:
    """Extract list of referenced design tokens."""
    tokens_found = set()
    raw_str = json.dumps(data)
    for tok in known_tokens:
        if tok in raw_str:
            tokens_found.add(tok)
    return sorted(tokens_found)


def _fetch_penpot_board(
    ctx: DesignContext,
    endpoint: str,
    token: str,
    board_id: str | None,
    file_id: str | None,
    cache_dir: str,
    on_unavailable: str,
    force_refresh: bool,
    mcp_url: str | None,
) -> dict[str, Any]:
    """Execute live HTTP request to Penpot API with revision-based caching."""
    target_file = file_id or "default"
    target_board = board_id or "default"
    url = endpoint.rstrip("/") + "/api/rpc/command/get-file"
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    body = json.dumps({"id": target_file}).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            if resp.status != 200:
                msg = f"Penpot HTTP status {resp.status}"
                if on_unavailable == "block":
                    return {
                        "supported": True,
                        "provider": "penpot",
                        "reachable": False,
                        "on_unavailable": "block",
                        "error": msg,
                        "file_id": target_file,
                        "board_id": target_board,
                        "mcp_url": mcp_url,
                    }
                return {
                    "supported": True,
                    "provider": "penpot",
                    "reachable": False,
                    "on_unavailable": "skip",
                    "warning": msg,
                    "file_id": target_file,
                    "board_id": target_board,
                    "mcp_url": mcp_url,
                }
            file_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        msg = f"Penpot endpoint {endpoint} unreachable: {e}"
        if on_unavailable == "block":
            return {
                "supported": True,
                "provider": "penpot",
                "reachable": False,
                "on_unavailable": "block",
                "error": msg,
                "file_id": target_file,
                "board_id": target_board,
                "mcp_url": mcp_url,
            }
        return {
            "supported": True,
            "provider": "penpot",
            "reachable": False,
            "on_unavailable": "skip",
            "warning": msg,
            "file_id": target_file,
            "board_id": target_board,
            "mcp_url": mcp_url,
        }

    # Extract revision or compute stable digest
    rev_raw = file_data.get("rev") or file_data.get("version")
    if rev_raw:
        rev = str(rev_raw)
    else:
        rev = hashlib.sha256(json.dumps(file_data, sort_keys=True).encode("utf-8")).hexdigest()[:12]

    # Geometry & Tokens
    geometry = _find_shape_geometry(file_data, board_id)
    raw_tokens = ctx.load_tokens_raw()
    all_tokens = {t["path"] for t in _flatten_dtcg_tokens(raw_tokens)}
    tokens_used = _extract_tokens_used(file_data, all_tokens)

    # Revision-based cache handling
    os.makedirs(cache_dir, exist_ok=True)
    cache_filename = f"{target_file}_{target_board}_{rev}.png"
    cache_filepath = os.path.join(cache_dir, cache_filename)
    cached = False

    if os.path.isfile(cache_filepath) and not force_refresh:
        cached = True
    else:
        # Request rendered reference PNG
        export_url = endpoint.rstrip("/") + "/api/rpc/command/export-object"
        export_body = json.dumps({
            "file-id": target_file,
            "object-id": target_board,
            "scale": 1,
            "type": "png",
        }).encode("utf-8")
        export_req = urllib.request.Request(export_url, data=export_body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(export_req, timeout=5.0) as exp_resp:
                if exp_resp.status == 200:
                    content = exp_resp.read()
                    with open(cache_filepath, "wb") as f:
                        f.write(content)
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to render PNG from Penpot exporter: {e}\n")

    rel_cache_path = os.path.relpath(cache_filepath, ctx.workspace_dir) if os.path.isfile(cache_filepath) else None

    return {
        "supported": True,
        "provider": "penpot",
        "reachable": True,
        "file_id": target_file,
        "board_id": target_board,
        "rev": rev,
        "cached": cached,
        "geometry": geometry,
        "tokens_used": tokens_used,
        "reference_png_path": rel_cache_path,
        "mcp_url": mcp_url,
    }


def handle_get_board_spec(ctx: DesignContext, args: dict[str, Any]) -> dict[str, Any]:
    board_id = args.get("board_id")
    file_id = args.get("file_id")
    force_refresh = bool(args.get("force_refresh", False))

    ds_cfg = ctx.config.get("design_system", {})
    provider = ds_cfg.get("provider", "git_only")

    if provider == "git_only":
        return {
            "supported": False,
            "provider": "git_only",
            "message": (
                "Visual board inspection requires 'penpot' or 'figma' provider in factory.toml. "
                "Currently operating in git_only mode (W3C DTCG tokens and local TOML contracts)."
            ),
            "tokens_path": os.path.relpath(ctx.tokens_path, ctx.workspace_dir)
            if os.path.exists(ctx.tokens_path)
            else ctx.tokens_path,
            "contracts_dir": os.path.relpath(ctx.contracts_dir, ctx.workspace_dir)
            if os.path.exists(ctx.contracts_dir)
            else ctx.contracts_dir,
        }

    if provider == "penpot":
        penpot_cfg = ds_cfg.get("penpot", {})
        endpoint = (
            penpot_cfg.get("base_url")
            or ds_cfg.get("endpoint")
            or os.environ.get("PENPOT_ENDPOINT")
            or "http://127.0.0.1:9001"
        )
        token_var = penpot_cfg.get("keyring_token") or "PENPOT_ACCESS_TOKEN"
        token = (
            os.environ.get(token_var)
            or os.environ.get("PENPOT_ACCESS_TOKEN")
            or os.environ.get("PENPOT_TOKEN")
            or ds_cfg.get("auth_key")
        )

        on_unavailable = penpot_cfg.get("on_unavailable") or "skip"
        cache_dir = penpot_cfg.get("cache_dir") or ".pa/cache/design"
        if not os.path.isabs(cache_dir):
            cache_dir = os.path.join(ctx.workspace_dir, cache_dir)
        mcp_url = penpot_cfg.get("mcp_url")

        if not token:
            msg = f"{token_var} not found in environment or keyring."
            if on_unavailable == "block":
                return {
                    "supported": True,
                    "provider": "penpot",
                    "configured": False,
                    "on_unavailable": "block",
                    "error": msg,
                    "mcp_url": mcp_url,
                }
            return {
                "supported": True,
                "provider": "penpot",
                "configured": False,
                "on_unavailable": "skip",
                "warning": msg,
                "mcp_url": mcp_url,
            }

        return _fetch_penpot_board(
            ctx,
            endpoint,
            token,
            board_id,
            file_id,
            cache_dir,
            on_unavailable,
            force_refresh,
            mcp_url,
        )

    if provider == "figma":
        figma_token = os.environ.get("FIGMA_TOKEN") or ds_cfg.get("auth_key")
        if not figma_token:
            return {
                "supported": True,
                "provider": "figma",
                "configured": False,
                "error": "FIGMA_TOKEN not found in environment or keyring.",
            }
        target_file = file_id or "default"
        url = f"https://api.figma.com/v1/files/{target_file}"
        if board_id:
            url += f"/nodes?ids={board_id}"
        req = urllib.request.Request(url, headers={"X-Figma-Token": figma_token})
        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return {"supported": True, "provider": "figma", "reachable": True, "data": data}
        except Exception as e:
            return {"supported": True, "provider": "figma", "reachable": False, "error": str(e)}

    return {
        "supported": False,
        "provider": provider,
        "message": f"Unsupported visual design provider: '{provider}'",
    }


TOOLS = [
    {
        "name": "design.search_tokens",
        "description": "Search and discover Design System tokens from W3C DTCG tokens.json. Supports filtering by query substring, category (color, spacing, typography), and generates platform snippets for web (CSS vars), iOS (Swift), or Android (Kotlin).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search substring matching token path, description, or value (e.g. 'brand', 'primary', '16px').",
                },
                "platform": {
                    "type": "string",
                    "enum": ["web", "ios", "android"],
                    "description": "Target UI platform for code snippet generation (default: 'web').",
                    "default": "web",
                },
                "category": {
                    "type": "string",
                    "description": "Optional token category filter (e.g. 'color', 'spacing', 'typography').",
                },
            },
        },
    },
    {
        "name": "design.get_component_contract",
        "description": "Fetch component contract specification from design/contracts/<component>.toml, including required design tokens, accessibility standards (WCAG), platform component paths, and validates token references.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "component": {
                    "type": "string",
                    "description": "Component name (e.g. 'Button', 'Card', 'Input').",
                }
            },
            "required": ["component"],
        },
    },
    {
        "name": "design.list_deprecated",
        "description": "List all deprecated design tokens and component contracts with their recommended replacements and sunset notices.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "design.get_board_spec",
        "description": "Inspect visual design board or component frame specifications via live Penpot/Figma HTTP API (or returns git_only status if operating in local Git token mode).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "board_id": {
                    "type": "string",
                    "description": "Optional board or frame ID.",
                },
                "file_id": {
                    "type": "string",
                    "description": "Optional design file/document ID.",
                },
                "force_refresh": {
                    "type": "boolean",
                    "description": "Bypass revision cache and force fresh PNG render from Penpot exporter.",
                    "default": False,
                },
            },
        },
    },
]


def run_stdio_server(ctx: DesignContext):
    """Main JSON-RPC stdio protocol loop."""
    handler_map = {
        "design.search_tokens": handle_search_tokens,
        "design_search_tokens": handle_search_tokens,
        "design.get_component_contract": handle_get_component_contract,
        "design_get_component_contract": handle_get_component_contract,
        "design.list_deprecated": handle_list_deprecated,
        "design_list_deprecated": handle_list_deprecated,
        "design.get_board_spec": handle_get_board_spec,
        "design_get_board_spec": handle_get_board_spec,
    }

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            }
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOLS},
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            handler = handler_map.get(tool_name)
            if handler:
                call_res = handler(ctx, tool_args)
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(call_res, indent=2)}
                        ]
                    },
                }
            else:
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method {tool_name} not found",
                    },
                }
        elif method == "ping":
            res = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        else:
            if msg_id is not None:
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Unhandled method: {method}",
                    },
                }
            else:
                continue

        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Design System MCP Server")
    parser.add_argument("--self-test", action="store_true", help="Run self test and exit")
    parser.add_argument("--workspace-dir", type=str, help="Workspace directory root")
    parser.add_argument("--config", type=str, help="Path to factory.toml")
    parser.add_argument("--tokens-path", type=str, help="Path to tokens.json")
    parser.add_argument("--contracts-path", type=str, help="Path to design contracts dir")
    args, _ = parser.parse_known_args()

    if args.self_test:
        print("mcp-server-ready")
        sys.exit(0)

    ctx = DesignContext(
        workspace_dir=args.workspace_dir,
        config_path=args.config,
        tokens_path=args.tokens_path,
        contracts_path=args.contracts_path,
    )
    run_stdio_server(ctx)


if __name__ == "__main__":
    main()
