"""
Capacity Planning Digital Twin MCP Server
=====================================================
Local stdio MCP server exposing all DuckDB gold layer tables and views
as structured tools for LangGraph agents.

Run directly:
    uv run python -m agentic.mcp_server.server

Or register in Claude Desktop claude_desktop_config.json:
    {
      "mcpServers": {
        "capacity-twin": {
          "command": "uv",
          "args": ["run", "python", "-m", "agentic.mcp_server.server"],
          "cwd": "<absolute path to capacity_planning_digital_twin>"
        }
      }
    }
"""

import json
import sys
import traceback
from typing import Any

# ── Tool imports ─────────────────────────────────────────────────────────────
from agentic.mcp_server.tools.schema_tools import (
    list_tables,
    get_schema,
    get_table_preview,
    get_distinct_values,
)
from agentic.mcp_server.tools.capacity_tools import (
    get_capacity_summary,
    get_bottleneck_analysis,
    get_demand_vs_supply,
    get_equipment_utilization,
)
from agentic.mcp_server.tools.yield_tools import (
    get_yield_prediction,
    get_yield_drivers,
    get_ml_adjusted_capacity,
)
from agentic.mcp_server.tools.maintenance_tools import (
    get_maintenance_alerts,
    get_failure_risk_trend,
)
from agentic.mcp_server.tools.forecast_tools import (
    get_demand_forecast,
    get_forecast_accuracy,
)
from agentic.mcp_server.tools.capex_tools import (
    get_capex_recommendation,
    get_capex_scenarios,
)
from agentic.mcp_server.tools.query_tool import run_query


# ── Tool registry ─────────────────────────────────────────────────────────────
# Maps tool name → (function, description, parameter schema)

TOOL_REGISTRY: dict[str, dict] = {

    # ── Schema discovery ──────────────────────────────────────────────────────
    "list_tables": {
        "fn": list_tables,
        "description": "List all gold tables and serving views in the DuckDB analytics layer.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    "get_schema": {
        "fn": get_schema,
        "description": "Return column names and types for a given table or view.",
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string", "description": "Table or view name, e.g. 'gold_bottleneck'"},
            },
            "required": ["table_name"],
        },
    },
    "get_table_preview": {
        "fn": get_table_preview,
        "description": "Return a small sample of rows from a table or view to understand data shape.",
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string"},
                "limit":      {"type": "integer", "default": 5},
            },
            "required": ["table_name"],
        },
    },
    "get_distinct_values": {
        "fn": get_distinct_values,
        "description": "Return distinct values for a column (e.g. all valid site_codes or test_types).",
        "parameters": {
            "type": "object",
            "properties": {
                "table_name":  {"type": "string"},
                "column_name": {"type": "string"},
                "limit":       {"type": "integer", "default": 50},
            },
            "required": ["table_name", "column_name"],
        },
    },

    # ── Capacity ──────────────────────────────────────────────────────────────
    "get_capacity_summary": {
        "fn": get_capacity_summary,
        "description": "Return capacity utilization, supply, demand and gap % per site × test_type × month.",
        "parameters": {
            "type": "object",
            "properties": {
                "site_code":  {"type": "string", "description": "Site code e.g. 'SG01'"},
                "month_from": {"type": "integer", "description": "Start month yyyymm e.g. 202301"},
                "month_to":   {"type": "integer", "description": "End month yyyymm e.g. 202312"},
                "limit":      {"type": "integer", "default": 100},
            },
            "required": [],
        },
    },
    "get_bottleneck_analysis": {
        "fn": get_bottleneck_analysis,
        "description": "Return bottleneck analysis by site and test type. Severity: CRITICAL/HIGH/MEDIUM/LOW/BALANCED/EXCESS.",
        "parameters": {
            "type": "object",
            "properties": {
                "site_code":  {"type": "string"},
                "severity":   {"type": "string", "enum": ["CRITICAL","HIGH","MEDIUM","LOW","BALANCED","EXCESS"]},
                "month_from": {"type": "integer"},
                "month_to":   {"type": "integer"},
                "limit":      {"type": "integer", "default": 100},
            },
            "required": [],
        },
    },
    "get_demand_vs_supply": {
        "fn": get_demand_vs_supply,
        "description": "Return demand vs supply comparison over time per product × site.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_number": {"type": "string"},
                "site_code":      {"type": "string"},
                "month_from":     {"type": "integer"},
                "month_to":       {"type": "integer"},
                "limit":          {"type": "integer", "default": 200},
            },
            "required": [],
        },
    },
    "get_equipment_utilization": {
        "fn": get_equipment_utilization,
        "description": "Return equipment utilization summary from the serving view.",
        "parameters": {
            "type": "object",
            "properties": {
                "site_code": {"type": "string"},
                "test_type": {"type": "string", "description": "e.g. OTA / TRX / PIM / PAM / FCT / ICT / BIT / ALT / UC / AT"},
                "limit":     {"type": "integer", "default": 100},
            },
            "required": [],
        },
    },

    # ── Yield ─────────────────────────────────────────────────────────────────
    "get_yield_prediction": {
        "fn": get_yield_prediction,
        "description": "Return ML-predicted yield vs actual yield per site × test_type × product × month.",
        "parameters": {
            "type": "object",
            "properties": {
                "site_code":      {"type": "string"},
                "test_type":      {"type": "string"},
                "product_number": {"type": "string"},
                "month_from":     {"type": "integer"},
                "month_to":       {"type": "integer"},
                "limit":          {"type": "integer", "default": 200},
            },
            "required": [],
        },
    },
    "get_yield_drivers": {
        "fn": get_yield_drivers,
        "description": "Return top SHAP features explaining yield loss or gain for a site × test_type.",
        "parameters": {
            "type": "object",
            "properties": {
                "site_code": {"type": "string"},
                "test_type": {"type": "string"},
                "top_n":     {"type": "integer", "default": 10},
            },
            "required": [],
        },
    },
    "get_ml_adjusted_capacity": {
        "fn": get_ml_adjusted_capacity,
        "description": "Return capacity recalculated using ML-predicted yield instead of static baseline yield.",
        "parameters": {
            "type": "object",
            "properties": {
                "site_code":  {"type": "string"},
                "test_type":  {"type": "string"},
                "month_from": {"type": "integer"},
                "month_to":   {"type": "integer"},
                "limit":      {"type": "integer", "default": 200},
            },
            "required": [],
        },
    },

    # ── Maintenance ───────────────────────────────────────────────────────────
    "get_maintenance_alerts": {
        "fn": get_maintenance_alerts,
        "description": "Return HIGH / CRITICAL predictive maintenance alerts for equipment.",
        "parameters": {
            "type": "object",
            "properties": {
                "site_code":  {"type": "string"},
                "test_type":  {"type": "string"},
                "risk_tier":  {"type": "string", "enum": ["HIGH", "CRITICAL"]},
                "month_from": {"type": "integer"},
                "month_to":   {"type": "integer"},
                "limit":      {"type": "integer", "default": 200},
            },
            "required": [],
        },
    },
    "get_failure_risk_trend": {
        "fn": get_failure_risk_trend,
        "description": "Return equipment failure probability trend over time for a site × test_type.",
        "parameters": {
            "type": "object",
            "properties": {
                "site_code":  {"type": "string"},
                "test_type":  {"type": "string"},
                "month_from": {"type": "integer"},
                "month_to":   {"type": "integer"},
                "limit":      {"type": "integer", "default": 200},
            },
            "required": [],
        },
    },

    # ── Forecast ──────────────────────────────────────────────────────────────
    "get_demand_forecast": {
        "fn": get_demand_forecast,
        "description": "Return 18-month demand forecast per product × site.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_number":  {"type": "string"},
                "site_code":       {"type": "string"},
                "month_from":      {"type": "integer"},
                "month_to":        {"type": "integer"},
                "forecast_method": {"type": "string", "enum": ["ensemble", "croston"]},
                "limit":           {"type": "integer", "default": 200},
            },
            "required": [],
        },
    },
    "get_forecast_accuracy": {
        "fn": get_forecast_accuracy,
        "description": "Return backtested forecast accuracy metrics (MAPE, SMAPE, RMSE, MAE) per product × site.",
        "parameters": {
            "type": "object",
            "properties": {
                "product_number": {"type": "string"},
                "site_code":      {"type": "string"},
                "limit":          {"type": "integer", "default": 100},
            },
            "required": [],
        },
    },

    # ── CapEx ─────────────────────────────────────────────────────────────────
    "get_capex_recommendation": {
        "fn": get_capex_recommendation,
        "description": "Return P50/P80/P95 Monte Carlo equipment quantity recommendations and USD CapEx.",
        "parameters": {
            "type": "object",
            "properties": {
                "site_code": {"type": "string"},
                "test_type": {"type": "string"},
                "limit":     {"type": "integer", "default": 100},
            },
            "required": [],
        },
    },
    "get_capex_scenarios": {
        "fn": get_capex_scenarios,
        "description": "Return underinvest / target / overinvest scenario comparison per site × test_type.",
        "parameters": {
            "type": "object",
            "properties": {
                "site_code": {"type": "string"},
                "test_type": {"type": "string"},
                "limit":     {"type": "integer", "default": 200},
            },
            "required": [],
        },
    },

    # ── Fallback ──────────────────────────────────────────────────────────────
    "run_query": {
        "fn": run_query,
        "description": (
            "Execute any read-only SQL SELECT query against the DuckDB gold layer. "
            "Use this as a fallback when no pre-defined tool matches the question. "
            "Only SELECT statements are permitted."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql":   {"type": "string", "description": "A SELECT SQL statement"},
                "limit": {"type": "integer", "default": 500},
            },
            "required": ["sql"],
        },
    },
}


# ── MCP stdio protocol ────────────────────────────────────────────────────────

def _send(msg: dict) -> None:
    """Write a JSON-RPC message to stdout."""
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _error(id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id,
            "error": {"code": code, "message": message}}


def handle_request(req: dict) -> dict | None:
    method = req.get("method", "")
    id_    = req.get("id")
    params = req.get("params", {})

    # ── Handshake ─────────────────────────────────────────────────────────────
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": id_,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "capacity-planning-twin",
                    "version": "1.0.0",
                    "description": (
                        "MCP server for the Capacity Planning Digital Twin. "
                        "Exposes DuckDB gold layer tables and ML outputs as "
                        "structured tools for LangGraph agents."
                    ),
                },
            },
        }

    if method == "notifications/initialized":
        return None  # No response needed for notifications

    # ── Tool listing ──────────────────────────────────────────────────────────
    if method == "tools/list":
        tools = []
        for name, meta in TOOL_REGISTRY.items():
            tools.append({
                "name": name,
                "description": meta["description"],
                "inputSchema": meta["parameters"],
            })
        return {"jsonrpc": "2.0", "id": id_, "result": {"tools": tools}}

    # ── Tool execution ────────────────────────────────────────────────────────
    if method == "tools/call":
        tool_name = params.get("name", "")
        args      = params.get("arguments", {})

        if tool_name not in TOOL_REGISTRY:
            return _error(id_, -32601, f"Unknown tool: {tool_name}")

        fn = TOOL_REGISTRY[tool_name]["fn"]
        try:
            result = fn(**args)
            return {
                "jsonrpc": "2.0", "id": id_,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(result, default=str)}
                    ]
                },
            }
        except Exception as e:
            tb = traceback.format_exc()
            return _error(id_, -32603, f"Tool execution failed: {e}\n{tb}")

    # ── Unknown method ────────────────────────────────────────────────────────
    return _error(id_, -32601, f"Method not found: {method}")


def main() -> None:
    """Main stdio loop — reads JSON-RPC lines from stdin, writes to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            _send(_error(None, -32700, f"Parse error: {e}"))
            continue

        try:
            response = handle_request(req)
            if response is not None:
                _send(response)
        except Exception as e:
            _send(_error(req.get("id"), -32603, f"Internal error: {e}"))


if __name__ == "__main__":
    main()
