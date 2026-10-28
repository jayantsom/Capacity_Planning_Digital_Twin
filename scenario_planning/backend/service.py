"""Serving-only baseline queries for browser-session scenarios."""

from __future__ import annotations

from typing import Any

from capacity_twin_core.planning.runtime import (
    health_payload,
    option,
    release_payload,
    rows,
    serving_connection,
)
from capacity_twin_core.runtime.database_paths import load_app_config
from scenario_planning.backend.models import ScenarioFilters

CONFIG = load_app_config("scenario_planning")
REQUIRED = frozenset(CONFIG["query"]["required_serving_tables"])
MAX_POINTS = int(CONFIG["query"]["maximum_chart_points"])
MAX_ROWS = int(CONFIG["query"]["maximum_table_rows"])

LEVERS = [
    {
        "code": "demand",
        "label": "Demand multiplier",
        "unit": "MULTIPLIER",
        "default": 1.0,
        "applies_to": "demand",
    },
    {
        "code": "yield",
        "label": "Yield multiplier",
        "unit": "MULTIPLIER",
        "default": 1.0,
        "applies_to": "capacity",
    },
    {
        "code": "oee",
        "label": "OEE multiplier",
        "unit": "MULTIPLIER",
        "default": 1.0,
        "applies_to": "capacity",
    },
    {
        "code": "shifts",
        "label": "Shift multiplier",
        "unit": "MULTIPLIER",
        "default": 1.0,
        "applies_to": "capacity",
    },
    {
        "code": "equipment",
        "label": "Additional equipment",
        "unit": "COUNT",
        "default": 0.0,
        "applies_to": "capacity",
    },
    {
        "code": "retest",
        "label": "Retest workload rate",
        "unit": "PCT",
        "default": 0.0,
        "applies_to": "demand",
    },
    {
        "code": "allocation",
        "label": "Shared-resource allocation multiplier",
        "unit": "MULTIPLIER",
        "default": 1.0,
        "applies_to": "capacity",
    },
    {
        "code": "overtime",
        "label": "Overtime rate",
        "unit": "PCT",
        "default": 0.0,
        "applies_to": "capacity",
    },
]


def _where(filters: ScenarioFilters, alias: str = "") -> tuple[str, list[Any]]:
    prefix = f"{alias}." if alias else ""
    clauses, params = [], []
    for column, value in (
        ("site_code", filters.site),
        ("product_number", filters.product),
        ("planning_version_id", filters.planning_version),
    ):
        if value:
            clauses.append(f"{prefix}{column} = ?")
            params.append(value)
    if filters.month_from is not None:
        clauses.append(f"CAST({prefix}month_key AS INTEGER) >= ?")
        params.append(filters.month_from)
    if filters.month_to is not None:
        clauses.append(f"CAST({prefix}month_key AS INTEGER) <= ?")
        params.append(filters.month_to)
    return " AND ".join(clauses) or "TRUE", params


def health() -> dict[str, Any]:
    return health_payload("scenario-planning", REQUIRED)


def filters_payload() -> dict[str, Any]:
    with serving_connection(REQUIRED) as (connection, snapshot):
        sites = rows(
            connection,
            "SELECT site_code, MAX(site_name) AS label FROM srv_vw_capacity_summary "
            "GROUP BY site_code ORDER BY label LIMIT 200",
        )
        products = rows(
            connection,
            "SELECT product_number, MAX(product_description) AS label "
            "FROM srv_vw_capacity_summary GROUP BY product_number ORDER BY label LIMIT 500",
        )
        versions = rows(
            connection,
            "SELECT planning_version_id, MAX(plan_as_of_date) AS plan_as_of_date "
            "FROM srv_vw_capacity_summary GROUP BY planning_version_id "
            "ORDER BY plan_as_of_date DESC LIMIT 200",
        )
        month_range = connection.execute(
            "SELECT MIN(CAST(month_key AS INTEGER)), MAX(CAST(month_key AS INTEGER)) "
            "FROM srv_vw_capacity_summary"
        ).fetchone()
    return {
        "status": "ready",
        "release": release_payload(snapshot),
        "applicable": ["site", "product", "planning_version", "month_from", "month_to"],
        "options": {
            "site": [option(row["site_code"], row["label"]) for row in sites],
            "product": [option(row["product_number"], row["label"]) for row in products],
            "planning_version": [
                option(row["planning_version_id"], f"Plan as of {row['plan_as_of_date']}")
                for row in versions
            ],
        },
        "month_range": {"minimum": month_range[0], "maximum": month_range[1], "grain": "MONTH"},
    }


def baseline_payload(filters: ScenarioFilters) -> dict[str, Any]:
    where, params = _where(filters)
    with serving_connection(REQUIRED) as (connection, snapshot):
        trend = rows(
            connection,
            f"""
            SELECT CAST(month_key AS INTEGER) AS month,
                   SUM(demand_qty) AS baseline_demand_ea,
                   SUM(capacity_qty) AS baseline_capacity_ea,
                   SUM(gap_qty) AS baseline_gap_ea
            FROM srv_vw_capacity_summary
            WHERE capacity_mode = 'NORMAL' AND retest_type = 'NONE' AND {where}
            GROUP BY month_key ORDER BY month_key LIMIT {MAX_POINTS}
            """,
            params,
        )
        constraints = rows(
            connection,
            f"""
            SELECT CAST(month_key AS INTEGER) AS month, site_code, site_name,
                   product_number, product_description, test_type, test_category_name,
                   resource_constraint_id, equipment_name, resource_behavior,
                   equipment_type, required_resource_hours, available_resource_hours,
                   gap_resource_hours, bottleneck_severity
            FROM srv_resource_constraints
            WHERE capacity_mode = 'NORMAL' AND retest_type = 'NONE' AND {where}
            ORDER BY gap_resource_hours, month_key LIMIT {MAX_ROWS}
            """,
            params,
        )
        source_inputs = rows(
            connection,
            f"""
            SELECT assumption_type, unit_code, COUNT(*) AS source_row_count,
                   SUM(baseline_value) AS baseline_value,
                   MIN(lower_bound) AS lower_bound, MAX(upper_bound) AS upper_bound
            FROM srv_scenario_inputs
            WHERE {where}
            GROUP BY assumption_type, unit_code ORDER BY assumption_type
            """,
            params,
        )
    demand = sum(float(row["baseline_demand_ea"] or 0) for row in trend)
    capacity = sum(float(row["baseline_capacity_ea"] or 0) for row in trend)
    return {
        "status": "ready" if trend else "empty",
        "message": None if trend else "No scenario baseline matches the selected filters.",
        "release": release_payload(snapshot),
        "filters": filters.model_dump(),
        "grain": "MONTH",
        "unit": "EA",
        "kpis": {
            "baseline_demand_ea": demand,
            "baseline_capacity_ea": capacity,
            "baseline_gap_ea": capacity - demand,
            "baseline_utilization_pct": demand / capacity if capacity else None,
        },
        "trend": trend,
        "affected_resources": constraints,
        "source_inputs": source_inputs,
        "assumptions": [
            {
                **lever,
                "minimum": CONFIG["scenario"]["assumption_bounds"][lever["code"]][0],
                "maximum": CONFIG["scenario"]["assumption_bounds"][lever["code"]][1],
            }
            for lever in LEVERS
        ],
        "scenario_model": {
            "schema_version": CONFIG["scenario"]["schema_version"],
            "scope": "browser-session-only",
            "server_persistence": False,
            "formula": {
                "scenario_demand": "baseline_demand * demand * (1 + retest)",
                "scenario_capacity": (
                    "baseline_capacity * yield * oee * shifts * allocation "
                    "* (1 + overtime) + equipment * baseline_capacity_per_resource"
                ),
                "baseline_capacity_per_resource": (
                    "baseline_capacity / distinct affected resources; zero when unavailable"
                ),
            },
            "limitations": [
                "Scenario outputs are deterministic what-if model results, not measured facts.",
                "Cost and service trade-offs are excluded because governed trade-off facts are absent.",
                "Assumptions are stored only in this browser session.",
            ],
        },
        "limits": {"chart_points": MAX_POINTS, "table_rows": MAX_ROWS},
    }
