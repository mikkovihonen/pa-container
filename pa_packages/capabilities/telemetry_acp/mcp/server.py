#!/usr/bin/env python3
"""Factory Telemetry Model Context Protocol (MCP) Server.

Provides structured JSON-RPC tools over stdio for querying factory operational
telemetry, OKR alignment, factory health (FPY, CFR, DORA), recent failure diagnostics,
and SLO defense mode status.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SERVER_NAME = "telemetry_acp"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"


class TelemetryContext:
    def __init__(
        self,
        workspace_dir: str | None = None,
        config_path: str | None = None,
        db_path: str | None = None,
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

        self.db_path = db_path or os.environ.get("PA_FACTORY_DB")
        if not self.db_path:
            self.db_path = os.path.join(self.workspace_dir, ".pa", "factory.db")

        self.config: dict[str, Any] = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        if self.config_path and os.path.isfile(self.config_path):
            try:
                with open(self.config_path, "rb") as f:
                    return tomllib.load(f)
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to parse {self.config_path}: {e}\n")
        return {}

    def get_db_connection(self) -> sqlite3.Connection | None:
        if not os.path.isfile(self.db_path):
            return None
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to connect to DB at {self.db_path}: {e}\n")
            return None


def handle_get_okr_context(ctx: TelemetryContext, args: dict[str, Any]) -> dict[str, Any]:
    kr_id = args.get("kr_id", "").strip()
    if not kr_id:
        return {"error": "kr_id is required"}

    # 1. Search docs/okrs/*.toml for kr_id
    okrs_dir = os.path.join(ctx.workspace_dir, "docs", "okrs")
    matched_kr: dict[str, Any] | None = None
    matched_obj: dict[str, Any] | None = None
    matched_file: str | None = None

    if os.path.isdir(okrs_dir):
        for toml_path in glob.glob(os.path.join(okrs_dir, "*.toml")):
            try:
                with open(toml_path, "rb") as f:
                    data = tomllib.load(f)
                obj = data.get("objective", {})
                for kr in data.get("key_results", []):
                    if kr.get("id") == kr_id:
                        matched_kr = kr
                        matched_obj = obj
                        matched_file = os.path.relpath(toml_path, ctx.workspace_dir)
                        break
            except Exception as e:
                sys.stderr.write(f"Warning: error reading {toml_path}: {e}\n")
            if matched_kr:
                break

    if not matched_kr:
        return {
            "found": False,
            "kr_id": kr_id,
            "message": f"Key Result '{kr_id}' not found in docs/okrs/*.toml",
        }

    baseline = float(matched_kr.get("baseline", 0.0))
    target = float(matched_kr.get("target", 100.0))
    current = float(matched_kr.get("current", baseline))
    budget_usd = float(matched_kr.get("budget_usd", 50.0))

    if abs(target - baseline) > 1e-6:
        calculated_progress = max(0.0, min(100.0, ((current - baseline) / (target - baseline)) * 100.0))
    else:
        calculated_progress = 100.0 if current >= target else 0.0

    result: dict[str, Any] = {
        "found": True,
        "kr_id": kr_id,
        "title": matched_kr.get("title", ""),
        "metric_query": matched_kr.get("metric_query", ""),
        "baseline": baseline,
        "target": target,
        "current": current,
        "progress_pct": round(calculated_progress, 2),
        "budget_usd": budget_usd,
        "linked_reqs": matched_kr.get("linked_reqs", []),
        "source_file": matched_file,
        "objective": {
            "id": matched_obj.get("id") if matched_obj else None,
            "title": matched_obj.get("title") if matched_obj else None,
            "owner": matched_obj.get("owner") if matched_obj else None,
            "budget_usd": matched_obj.get("budget_usd") if matched_obj else None,
        },
        "latest_snapshot": None,
        "task_summary": {
            "total_tasks": 0,
            "total_spend_usd": 0.0,
            "budget_utilization_pct": 0.0,
            "recent_tasks": [],
        },
    }

    # 2. Query factory.db if available
    conn = ctx.get_db_connection()
    if conn:
        try:
            # Latest snapshot
            snap_cur = conn.cursor()
            snap_cur.execute(
                "SELECT snapshot_id, observed_at, value, progress_pct, latest_deploy_sha "
                "FROM kr_snapshots WHERE kr_id = ? ORDER BY observed_at DESC LIMIT 1",
                (kr_id,),
            )
            row = snap_cur.fetchone()
            if row:
                result["latest_snapshot"] = {
                    "snapshot_id": row["snapshot_id"],
                    "observed_at": row["observed_at"],
                    "value": row["value"],
                    "progress_pct": row["progress_pct"],
                    "latest_deploy_sha": row["latest_deploy_sha"],
                }
                result["progress_pct"] = row["progress_pct"]
                result["current"] = row["value"]

            # Linked tasks
            task_cur = conn.cursor()
            task_cur.execute(
                "SELECT t.task_id, t.agent_role, t.model, t.cost_usd, t.status, t.created_at "
                "FROM tasks t "
                "JOIN task_krs tk ON t.task_id = tk.task_id "
                "WHERE tk.kr_id = ? "
                "ORDER BY t.created_at DESC",
                (kr_id,),
            )
            task_rows = task_cur.fetchall()
            total_spend = 0.0
            recent_tasks = []
            for tr in task_rows:
                cost = tr["cost_usd"] or 0.0
                total_spend += cost
                if len(recent_tasks) < 5:
                    recent_tasks.append(
                        {
                            "task_id": tr["task_id"],
                            "agent_role": tr["agent_role"],
                            "model": tr["model"],
                            "cost_usd": cost,
                            "status": tr["status"],
                            "created_at": tr["created_at"],
                        }
                    )

            utilization = (total_spend / budget_usd * 100.0) if budget_usd > 0 else 0.0
            result["task_summary"] = {
                "total_tasks": len(task_rows),
                "total_spend_usd": round(total_spend, 4),
                "budget_utilization_pct": round(utilization, 2),
                "recent_tasks": recent_tasks,
            }
        except Exception as e:
            sys.stderr.write(f"Warning: DB error querying KR context: {e}\n")
        finally:
            conn.close()

    return result


def _query_live_prometheus(endpoint: str, token: str | None) -> dict[str, Any]:
    url = endpoint.rstrip("/") + "/api/v1/query?query=up"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                return {
                    "reachable": True,
                    "endpoint": endpoint,
                    "status": payload.get("status", "unknown"),
                    "data": payload.get("data", {}),
                }
            return {"reachable": False, "endpoint": endpoint, "http_status": resp.status}
    except Exception as e:
        return {"reachable": False, "endpoint": endpoint, "error": str(e)}


def handle_get_factory_health(ctx: TelemetryContext, args: dict[str, Any]) -> dict[str, Any]:
    window_days = int(args.get("window_days", 30))

    # Read governance WIP limit from config
    gov_cfg = ctx.config.get("governance", {})
    max_wip_prs = gov_cfg.get("max_wip_prs", 5)

    fpy = 1.0
    cfr = 0.0
    total_tasks = 0
    successful_tasks = 0
    failed_tasks = 0
    open_prs = 0
    merged_prs = 0

    conn = ctx.get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            # Open PRs
            cur.execute("SELECT COUNT(*) FROM vcs_outcomes WHERE state = 'open'")
            open_prs = cur.fetchone()[0]

            # Merged PRs
            cur.execute("SELECT COUNT(*) FROM vcs_outcomes WHERE state = 'merged'")
            merged_prs = cur.fetchone()[0]

            # FPY calculation
            cur.execute(
                "SELECT human_review_rounds, human_commits_added, ci_failed_first_run, reverted "
                "FROM vcs_outcomes WHERE state = 'merged'"
            )
            vcs_rows = cur.fetchall()
            if vcs_rows:
                first_pass_count = sum(
                    1
                    for r in vcs_rows
                    if (r["human_review_rounds"] or 0) == 0
                    and (r["human_commits_added"] or 0) == 0
                    and not r["ci_failed_first_run"]
                    and not r["reverted"]
                )
                fpy = round(first_pass_count / len(vcs_rows), 4)

            # CFR calculation: incidents / deployments
            cur.execute("SELECT COUNT(*) FROM prod_signals")
            total_deploys = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM prod_signals WHERE incident_triggered = 1")
            incidents = cur.fetchone()[0]
            if total_deploys > 0:
                cfr = round(incidents / total_deploys, 4)
            elif vcs_rows:
                reverted_count = sum(1 for r in vcs_rows if r["reverted"])
                cfr = round(reverted_count / len(vcs_rows), 4)

            # Tasks summary
            cur.execute("SELECT COUNT(*) FROM tasks")
            total_tasks = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tasks WHERE status = 'success'")
            successful_tasks = cur.fetchone()[0]
            failed_tasks = total_tasks - successful_tasks
        except Exception as e:
            sys.stderr.write(f"Warning: DB error in get_factory_health: {e}\n")
        finally:
            conn.close()

    success_rate = (
        round((successful_tasks / total_tasks) * 100.0, 2) if total_tasks > 0 else 100.0
    )

    result: dict[str, Any] = {
        "status": "healthy" if fpy >= 0.8 and cfr <= 0.15 else "degraded",
        "window_days": window_days,
        "first_pass_yield": fpy,
        "change_failure_rate": cfr,
        "task_metrics": {
            "total_tasks": total_tasks,
            "successful_tasks": successful_tasks,
            "failed_tasks": failed_tasks,
            "success_rate_pct": success_rate,
        },
        "wip_pipeline": {
            "open_prs": open_prs,
            "max_wip_prs": max_wip_prs,
            "wip_saturated": open_prs >= max_wip_prs,
            "merged_prs": merged_prs,
        },
        "live_metrics": None,
    }

    # Upstream Prometheus check if configured
    telemetry_metrics = ctx.config.get("telemetry", {}).get("metrics", {})
    provider = telemetry_metrics.get("provider", "none")
    endpoint = telemetry_metrics.get("endpoint") or os.environ.get("PROMETHEUS_ENDPOINT")

    if provider == "prometheus" and endpoint:
        token = os.environ.get("PROMETHEUS_TOKEN")
        result["live_metrics"] = _query_live_prometheus(endpoint, token)
    else:
        result["live_metrics"] = {"configured": False, "provider": provider}

    return result


def _query_live_phoenix(endpoint: str, limit: int) -> dict[str, Any]:
    url = endpoint.rstrip("/") + f"/v1/traces?limit={limit}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                return {
                    "reachable": True,
                    "endpoint": endpoint,
                    "traces_count": len(payload.get("data", [])),
                    "traces": payload.get("data", [])[:limit],
                }
            return {"reachable": False, "endpoint": endpoint, "http_status": resp.status}
    except Exception as e:
        return {"reachable": False, "endpoint": endpoint, "error": str(e)}


def handle_query_recent_failures(ctx: TelemetryContext, args: dict[str, Any]) -> dict[str, Any]:
    limit = int(args.get("limit", 10))
    role_filter = args.get("role")

    db_failures = []
    conn = ctx.get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            query = (
                "SELECT task_id, agent_role, model, status, cost_usd, created_at "
                "FROM tasks WHERE status != 'success' "
            )
            params: list[Any] = []
            if role_filter:
                query += "AND agent_role = ? "
                params.append(role_filter)
            query += "ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cur.execute(query, params)
            for row in cur.fetchall():
                db_failures.append(
                    {
                        "task_id": row["task_id"],
                        "agent_role": row["agent_role"],
                        "model": row["model"],
                        "status": row["status"],
                        "cost_usd": row["cost_usd"],
                        "created_at": row["created_at"],
                    }
                )
        except Exception as e:
            sys.stderr.write(f"Warning: DB error in query_recent_failures: {e}\n")
        finally:
            conn.close()

    result: dict[str, Any] = {
        "failures_count": len(db_failures),
        "limit": limit,
        "role_filter": role_filter,
        "failures": db_failures,
        "live_traces": None,
    }

    # Upstream Phoenix check if configured
    otlp_spec = ctx.config.get("telemetry", {}).get("otlp", {})
    endpoint = (
        otlp_spec.get("endpoint")
        or os.environ.get("PHOENIX_ENDPOINT")
        or os.environ.get("PHOENIX_COLLECTOR_ENDPOINT")
    )
    if endpoint and ("6006" in endpoint or "phoenix" in endpoint.lower()):
        result["live_traces"] = _query_live_phoenix(endpoint, limit)
    else:
        result["live_traces"] = {"configured": False}

    return result


def handle_get_slo_status(ctx: TelemetryContext, _args: dict[str, Any]) -> dict[str, Any]:
    gov_cfg = ctx.config.get("governance", {})
    slo_target = float(gov_cfg.get("slo_defense_error_budget_min", 0.99))
    slo_target_pct = slo_target * 100.0
    on_slo_breach = gov_cfg.get("on_slo_breach", "block")
    allowed_roles = gov_cfg.get(
        "defense_mode_allowed_roles", ["bugfix", "triage", "verifier"]
    )

    success_rate = 100.0
    rolling_cfr = 0.0
    total_tasks = 0

    conn = ctx.get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT status FROM tasks ORDER BY created_at DESC LIMIT 20")
            recent_statuses = [r[0] for r in cur.fetchall()]
            total_tasks = len(recent_statuses)
            if total_tasks > 0:
                success_count = sum(1 for s in recent_statuses if s == "success")
                success_rate = round((success_count / total_tasks) * 100.0, 2)

            cur.execute("SELECT COUNT(*) FROM prod_signals")
            total_deploys = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM prod_signals WHERE incident_triggered = 1")
            incidents = cur.fetchone()[0]
            if total_deploys > 0:
                rolling_cfr = round(incidents / total_deploys, 4)
            else:
                cur.execute(
                    "SELECT COUNT(*), SUM(CASE WHEN reverted = 1 THEN 1 ELSE 0 END) "
                    "FROM vcs_outcomes WHERE state = 'merged'"
                )
                row = cur.fetchone()
                if row and row[0] and row[0] > 0:
                    rolling_cfr = round((row[1] or 0) / row[0], 4)
        except Exception as e:
            sys.stderr.write(f"Warning: DB error in get_slo_status: {e}\n")
        finally:
            conn.close()

    defense_mode_active = (success_rate < slo_target_pct) or (rolling_cfr > 0.20)
    budget_burn_pct = max(0.0, round(slo_target_pct - success_rate, 2))

    return {
        "status": "defense_mode" if defense_mode_active else "normal",
        "defense_mode_active": defense_mode_active,
        "slo_target_min_pct": slo_target_pct,
        "current_success_rate_pct": success_rate,
        "rolling_cfr": rolling_cfr,
        "error_budget_burn_pct": budget_burn_pct,
        "on_slo_breach": on_slo_breach,
        "defense_mode_allowed_roles": allowed_roles,
        "evaluation_sample_size": total_tasks,
    }


TOOLS = [
    {
        "name": "telemetry.get_okr_context",
        "description": "Fetch OKR context for a Key Result ID (reads docs/okrs/*.toml and .pa/factory.db). Returns objective title, KR baseline/target/current, calculated progress %, budget utilization, and recent tasks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kr_id": {
                    "type": "string",
                    "description": "Key Result ID (e.g. 'KR-AUTH-01').",
                }
            },
            "required": ["kr_id"],
        },
    },
    {
        "name": "telemetry.get_factory_health",
        "description": "Fetch factory health metrics: rolling First Pass Yield (FPY), Change Failure Rate (CFR), task success rate, open PR queue depth vs WIP limit, and live Prometheus status if configured.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "window_days": {
                    "type": "integer",
                    "description": "Rolling window in days (default: 30).",
                    "default": 30,
                }
            },
        },
    },
    {
        "name": "telemetry.query_recent_failures",
        "description": "Query recent task execution failures, verification gate breaches, and optional live OTLP/Phoenix traces.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of recent failures to return (default: 10).",
                    "default": 10,
                },
                "role": {
                    "type": "string",
                    "description": "Optional agent role filter (e.g. 'feature', 'bugfix', 'verifier').",
                },
            },
        },
    },
    {
        "name": "telemetry.get_slo_status",
        "description": "Evaluate SLO error budget health: returns whether SLO Defense Mode is active, current success rate vs target, rolling CFR, and list of allowed emergency roles.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def run_stdio_server(ctx: TelemetryContext):
    """Main JSON-RPC stdio protocol loop."""
    handler_map = {
        "telemetry.get_okr_context": handle_get_okr_context,
        "telemetry_get_okr_context": handle_get_okr_context,
        "telemetry.get_factory_health": handle_get_factory_health,
        "telemetry_get_factory_health": handle_get_factory_health,
        "telemetry.query_recent_failures": handle_query_recent_failures,
        "telemetry_query_recent_failures": handle_query_recent_failures,
        "telemetry.get_slo_status": handle_get_slo_status,
        "telemetry_get_slo_status": handle_get_slo_status,
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
    parser = argparse.ArgumentParser(description="Telemetry MCP Server")
    parser.add_argument("--self-test", action="store_true", help="Run self test and exit")
    parser.add_argument("--workspace-dir", type=str, help="Workspace directory root")
    parser.add_argument("--config", type=str, help="Path to factory.toml")
    parser.add_argument("--db-path", type=str, help="Path to SQLite factory.db")
    args, _ = parser.parse_known_args()

    if args.self_test:
        print("mcp-server-ready")
        sys.exit(0)

    ctx = TelemetryContext(
        workspace_dir=args.workspace_dir,
        config_path=args.config,
        db_path=args.db_path,
    )
    run_stdio_server(ctx)


if __name__ == "__main__":
    main()
