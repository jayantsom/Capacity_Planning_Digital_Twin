"""Reconciled Serving-only S&OP queries."""

from __future__ import annotations

from typing import Any, Literal

from capacity_twin_core.planning.runtime import (
    health_payload,
    option,
    release_payload,
    rows,
    serving_connection,
)
from capacity_twin_core.runtime.database_paths import load_app_config
from demand_supply_planning.backend.models import SopFilters

View = Literal["executive", "demand-planner", "capacity-planner"]
CONFIG = load_app_config("demand_supply_planning")
REQUIRED = frozenset(CONFIG["query"]["required_serving_tables"])
MAX_POINTS = int(CONFIG["query"]["maximum_chart_points"])
MAX_ROWS = int(CONFIG["query"]["maximum_table_rows"])


def _where(filters: SopFilters) -> tuple[str, list[Any]]:
    clauses, params = [], []
    for column, value in (
        ("site_code", filters.site),
        ("product_number", filters.product),
        ("planning_version_id", filters.planning_version),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if filters.month_from is not None:
        clauses.append("CAST(month_key AS INTEGER) >= ?")
        params.append(filters.month_from)
    if filters.month_to is not None:
        clauses.append("CAST(month_key AS INTEGER) <= ?")
        params.append(filters.month_to)
    return " AND ".join(clauses) or "TRUE", params


def health() -> dict[str, Any]:
    return health_payload("demand-supply-planning", REQUIRED)


def filters_payload(view: View) -> dict[str, Any]:
    with serving_connection(REQUIRED) as (connection, snapshot):
        sites = rows(
            connection,
            "SELECT site_code, MAX(site_name) AS label FROM srv_sop_balance "
            "GROUP BY site_code ORDER BY label LIMIT 200",
        )
        products = rows(
            connection,
            "SELECT product_number, MAX(product_description) AS label FROM srv_sop_balance "
            "GROUP BY product_number ORDER BY label LIMIT 500",
        )
        versions = rows(
            connection,
            "SELECT planning_version_id, MAX(plan_as_of_date) AS plan_as_of_date "
            "FROM srv_sop_balance GROUP BY planning_version_id "
            "ORDER BY plan_as_of_date DESC LIMIT 200",
        )
        months = connection.execute(
            "SELECT MIN(month_key), MAX(month_key) FROM srv_sop_balance"
        ).fetchone()
    return {
        "status": "ready",
        "view": view,
        "release": release_payload(snapshot),
        "applicable": ["site", "product", "planning_version", "month_from", "month_to"],
        "options": {
            "site": [option(row["site_code"], row["label"]) for row in sites],
            "product": [
                option(row["product_number"], row["label"])
                for row in products
            ],
            "planning_version": [
                option(row["planning_version_id"], f"Plan as of {row['plan_as_of_date']}")
                for row in versions
            ],
        },
        "month_range": {"minimum": months[0], "maximum": months[1], "grain": "MONTH"},
    }


def dashboard_payload(view: View, filters: SopFilters) -> dict[str, Any]:
    where, params = _where(filters)
    with serving_connection(REQUIRED) as (connection, snapshot):
        trend = rows(
            connection,
            f"""
            SELECT month_key AS month,
                   SUM(customer_order_quantity_ea) AS demand_ea,
                   SUM(constrained_production_ea) AS constrained_production_ea,
                   SUM(receipt_quantity_ea) AS receipts_ea,
                   SUM(shipment_quantity_ea) AS shipments_ea,
                   SUM(ending_inventory_ea) AS ending_inventory_ea,
                   SUM(ending_backlog_ea) AS ending_backlog_ea,
                   SUM(safety_stock_quantity_ea) AS safety_stock_ea,
                   AVG(inventory_coverage_months) AS inventory_coverage_months,
                   AVG(fill_rate_target_pct) AS fill_rate_target_pct
            FROM srv_sop_balance WHERE {where}
            GROUP BY month_key ORDER BY month_key LIMIT {MAX_POINTS}
            """,
            params,
        )
        exceptions = rows(
            connection,
            f"""
            SELECT site_code, site_name, product_number, product_description,
                   month_key, service_risk_status,
                   customer_order_quantity_ea, constrained_production_ea,
                   ending_inventory_ea, safety_stock_quantity_ea,
                   ending_backlog_ea, oldest_backlog_days,
                   inventory_coverage_months, fill_rate_target_pct,
                   inventory_balance_variance_ea
            FROM srv_sop_balance
            WHERE {where} AND service_risk_status != 'ON_TARGET'
            ORDER BY ending_backlog_ea DESC, oldest_backlog_days DESC
            LIMIT {MAX_ROWS}
            """,
            params,
        )
        reconciliation = rows(
            connection,
            f"""
            SELECT site_code, site_name, product_number, product_description, month_key,
                   beginning_inventory_ea, constrained_production_ea,
                   receipt_quantity_ea, shipment_quantity_ea,
                   ending_inventory_ea, calculated_ending_inventory_ea,
                   inventory_balance_variance_ea
            FROM srv_sop_balance WHERE {where}
            ORDER BY month_key, site_code, product_number LIMIT {MAX_ROWS}
            """,
            params,
        )
        allocation = rows(
            connection,
            f"""
            SELECT site_code, site_name, product_number, product_description,
                   month_key, resource_id, equipment_name,
                   SUM(baseline_value) AS allocated_resource_hours
            FROM srv_scenario_inputs
            WHERE assumption_type = 'SHARED_RESOURCE_HOURS' AND {where}
            GROUP BY site_code, site_name, product_number, product_description,
                     month_key, resource_id, equipment_name
            ORDER BY month_key, allocated_resource_hours DESC LIMIT {MAX_ROWS}
            """,
            params,
        )
    demand = sum(float(row["demand_ea"] or 0) for row in trend)
    supply = sum(float(row["constrained_production_ea"] or 0) for row in trend)
    shipments = sum(float(row["shipments_ea"] or 0) for row in trend)
    inventory = float(trend[-1]["ending_inventory_ea"] or 0) if trend else 0
    backlog = float(trend[-1]["ending_backlog_ea"] or 0) if trend else 0
    max_variance = max(
        (abs(float(row["inventory_balance_variance_ea"] or 0)) for row in reconciliation),
        default=0,
    )
    return {
        "status": "ready" if trend else "empty",
        "message": None if trend else "No S&OP data matches the selected filters.",
        "view": view,
        "release": release_payload(snapshot),
        "filters": filters.model_dump(),
        "grain": "MONTH",
        "unit": "EA",
        "kpis": {
            "demand_ea": demand,
            "constrained_production_ea": supply,
            "shipments_ea": shipments,
            "ending_inventory_ea": inventory,
            "ending_backlog_ea": backlog,
            "supply_demand_gap_ea": supply - demand,
            "exception_count": len(exceptions),
            "maximum_reconciliation_variance_ea": max_variance,
        },
        "trend": trend,
        "exceptions": exceptions,
        "reconciliation": reconciliation,
        "allocation": allocation,
        "action_register": {
            "scope": "browser-session-only",
            "schema_version": CONFIG["actions"]["schema_version"],
            "maximum_actions": CONFIG["actions"]["maximum_session_actions"],
            "server_persistence": False,
        },
        "limits": {"chart_points": MAX_POINTS, "table_rows": MAX_ROWS},
    }
