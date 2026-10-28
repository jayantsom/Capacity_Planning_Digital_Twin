"""
Domain Agents
=============
Five specialized agents, one per gold layer domain.
Each defines its own tools, system prompt, and name.
All inherit run() logic from BaseAgent.
"""

from typing import ClassVar

from operations_assistant.agentic.agents.base_agent import BaseAgent
from operations_assistant.agentic.mcp_server.tools.capacity_tools import (
    get_bottleneck_analysis,
    get_capacity_summary,
    get_demand_vs_supply,
    get_equipment_utilization,
)
from operations_assistant.agentic.mcp_server.tools.capex_tools import (
    get_capex_recommendation,
    get_capex_scenarios,
)
from operations_assistant.agentic.mcp_server.tools.forecast_tools import (
    get_demand_forecast,
    get_forecast_accuracy,
)
from operations_assistant.agentic.mcp_server.tools.maintenance_tools import (
    get_failure_risk_trend,
    get_maintenance_alerts,
)
from operations_assistant.agentic.mcp_server.tools.operational_tools import (
    get_operational_performance,
)
from operations_assistant.agentic.mcp_server.tools.query_tool import run_query

# MCP tool imports
from operations_assistant.agentic.mcp_server.tools.schema_tools import (
    get_distinct_values,
    get_schema,
    get_table_preview,
    list_tables,
)
from operations_assistant.agentic.mcp_server.tools.yield_tools import (
    get_ml_adjusted_capacity,
    get_yield_drivers,
    get_yield_prediction,
)

# ── Shared schema tools available to every agent ──────────────────────────────
_SCHEMA_TOOLS = {
    "list_tables":        list_tables,
    "get_schema":         get_schema,
    "get_table_preview":  get_table_preview,
    "get_distinct_values": get_distinct_values,
    "run_query":          run_query,
}


# ── 1. Capacity Agent ─────────────────────────────────────────────────────────

class CapacityAgent(BaseAgent):
    name        = "capacity"
    description = "Handles capacity utilization, bottlenecks, supply vs demand, and equipment planning."
    system_prompt = (
        "You are an expert in telecom and networking manufacturing capacity planning. "
        "You analyze equipment utilization, identify bottlenecks, and assess supply vs demand gaps. "
        "Key metrics: utilization_pct (>85% = constrained), gap_pct (negative = bottleneck), "
        "bottleneck_severity (CRITICAL/HIGH/MEDIUM/LOW/BALANCED/EXCESS). "
        "Capacity modes: NORMAL (standard shifts) and MAXIMUM (surge capacity). "
        "Use the promoted site, product, route, and test-type values returned by tools. "
        "Capacity planning is monthly; never present it as weekly data."
    )
    tools: ClassVar[dict] = {
        "get_capacity_summary":      get_capacity_summary,
        "get_bottleneck_analysis":   get_bottleneck_analysis,
        "get_demand_vs_supply":      get_demand_vs_supply,
        "get_equipment_utilization": get_equipment_utilization,
        **_SCHEMA_TOOLS,
    }


# ── 2. Yield Agent ────────────────────────────────────────────────────────────

class YieldAgent(BaseAgent):
    name        = "yield"
    description = "Handles yield predictions, yield loss drivers (SHAP), and ML-adjusted capacity."
    system_prompt = (
        "You are an expert in manufacturing yield analysis. "
        "You interpret ML-predicted yield rates, explain yield loss drivers via SHAP feature importance, "
        "and assess how yield variations shift capacity. "
        "Yield is expressed as a fraction (0–1), e.g. 0.85 = 85% first-pass yield. "
        "Lower yield → more retests → less effective capacity. "
        "SHAP values show which process parameters most impact yield: positive = increases yield, "
        "negative = reduces yield. "
        "gold_cap_ml_adjusted shows capacity recalculated with ML-predicted yield vs static baseline. "
        "Use operational performance for weekly yield; ML predictions remain monthly."
    )
    tools: ClassVar[dict] = {
        "get_yield_prediction":     get_yield_prediction,
        "get_yield_drivers":        get_yield_drivers,
        "get_ml_adjusted_capacity": get_ml_adjusted_capacity,
        "get_operational_performance": get_operational_performance,
        **_SCHEMA_TOOLS,
    }


# ── 3. Maintenance Agent ──────────────────────────────────────────────────────

class MaintenanceAgent(BaseAgent):
    name        = "maintenance"
    description = "Handles predictive maintenance alerts, failure risk trends, and OEE-based risk scoring."
    system_prompt = (
        "You are an expert in predictive maintenance for test and measurement equipment. "
        "You interpret failure probability scores (0–1) and risk tiers: "
        "LOW (<20%), MEDIUM (20–40%), HIGH (40–70%), CRITICAL (>70%). "
        "Failure is defined as OEE dropping below 88% within the next 3 months. "
        "OEE (Overall Equipment Effectiveness) ranges 0.81–0.98 in this dataset. "
        "Prioritize CRITICAL alerts — these need immediate attention. "
        "Trend analysis shows whether risk is increasing or stabilizing over time. "
        "Use operational performance for weekly OEE; risk predictions remain monthly."
    )
    tools: ClassVar[dict] = {
        "get_maintenance_alerts":  get_maintenance_alerts,
        "get_failure_risk_trend":  get_failure_risk_trend,
        "get_operational_performance": get_operational_performance,
        **_SCHEMA_TOOLS,
    }


# ── 4. Forecast Agent ─────────────────────────────────────────────────────────

class ForecastAgent(BaseAgent):
    name        = "forecast"
    description = "Handles demand forecasting and forecast accuracy metrics."
    system_prompt = (
        "You are an expert in manufacturing demand forecasting. "
        "You interpret the versioned demand forecasts and model metadata returned by tools. "
        "Forecast accuracy is measured by MAPE (Mean Absolute Percentage Error) — "
        "lower is better; <10% is good, 10–20% is acceptable, >20% needs review. "
        "Forecast months are integers in yyyymm format (e.g. 202307 = July 2023). "
        "Use exact product and site identifiers returned by tools. "
        "Demand forecasts are monthly; never invent weekly forecasts."
    )
    tools: ClassVar[dict] = {
        "get_demand_forecast":   get_demand_forecast,
        "get_forecast_accuracy": get_forecast_accuracy,
        **_SCHEMA_TOOLS,
    }


# ── 5. CapEx Agent ────────────────────────────────────────────────────────────

class CapExAgent(BaseAgent):
    name        = "capex"
    description = "Handles CapEx recommendations, Monte Carlo equipment planning, and investment scenarios."
    system_prompt = (
        "You are an expert in capital expenditure planning for test and measurement equipment. "
        "You interpret Monte Carlo simulation results and their declared sample count. "
        "Three planning levels are available: "
        "P50 (50th percentile — median demand scenario, lower cost, higher stockout risk), "
        "P80 (80th percentile — recommended planning target, balances cost vs risk), "
        "P95 (95th percentile — conservative, higher cost, near-zero stockout risk). "
        "Use versioned equipment costs returned by tools rather than assuming hard-coded prices. "
        "delta_units_p80 is additional equipment needed above current inventory. "
        "CapEx scenarios are atemporal site-test analyses, not weekly predictions."
    )
    tools: ClassVar[dict] = {
        "get_capex_recommendation": get_capex_recommendation,
        "get_capex_scenarios":      get_capex_scenarios,
        **_SCHEMA_TOOLS,
    }


# ── Agent registry ────────────────────────────────────────────────────────────

AGENT_REGISTRY: dict[str, BaseAgent] = {
    "capacity":    CapacityAgent(),
    "yield":       YieldAgent(),
    "maintenance": MaintenanceAgent(),
    "forecast":    ForecastAgent(),
    "capex":       CapExAgent(),
}
