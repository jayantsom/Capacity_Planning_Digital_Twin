"""Serving-only operations-flow measures derived from governed event facts."""

from __future__ import annotations

import statistics
from typing import Any, Literal

from capacity_twin_core.planning.runtime import (
    health_payload,
    option,
    release_payload,
    rows,
    serving_connection,
)
from capacity_twin_core.runtime.database_paths import load_app_config
from operations_flow.backend.models import FlowFilters

View = Literal["production-control", "industrial-engineering", "test-operations"]
CONFIG = load_app_config("operations_flow")
REQUIRED = frozenset(CONFIG["query"]["required_serving_tables"])
MAX_POINTS = int(CONFIG["query"]["maximum_chart_points"])
MAX_ROWS = int(CONFIG["query"]["maximum_table_rows"])

DATASET_FILTERS = {
    "wip": ["site", "product", "operation", "resource"],
    "queue": ["site", "operation", "resource", "date_from", "date_to"],
    "cycle_time": ["site", "product", "date_from", "date_to"],
    "throughput": ["site", "operation", "resource", "date_from", "date_to"],
    "rework": ["site", "product", "operation", "date_from", "date_to"],
    "route_adherence": ["site", "product"],
    "schedule_attainment": ["site", "product", "date_from", "date_to"],
    "bottleneck_movement": ["site", "operation", "resource", "date_from", "date_to"],
    "route_flow": [
        "site", "product", "operation", "resource", "date_from", "date_to",
    ],
}


def _predicate(
    filters: FlowFilters,
    mapping: dict[str, str],
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    values = {
        "site": filters.site,
        "product": filters.product,
        "operation": filters.operation,
        "resource": filters.resource,
        "date_from": filters.date_from,
        "date_to": filters.date_to,
    }
    for key, column in mapping.items():
        value = values[key]
        if value is None:
            continue
        if key == "date_from":
            clauses.append(f"CAST({column} AS DATE) >= ?")
        elif key == "date_to":
            clauses.append(f"CAST({column} AS DATE) <= ?")
        else:
            clauses.append(f"{column} = ?")
        params.append(value)
    return " AND ".join(clauses) or "TRUE", params


def health() -> dict[str, Any]:
    return health_payload("operations-flow", REQUIRED)


def filters_payload(view: View) -> dict[str, Any]:
    with serving_connection(REQUIRED) as (connection, snapshot):
        sites = rows(
            connection,
            "SELECT site_code, MAX(site_name) AS label FROM srv_operations_queue "
            "GROUP BY site_code ORDER BY label LIMIT 200",
        )
        products = rows(
            connection,
            "SELECT product_number, MAX(product_description) AS label "
            "FROM srv_operations_cycle_time GROUP BY product_number "
            "ORDER BY label LIMIT 500",
        )
        operations = rows(
            connection,
            "SELECT DISTINCT operation FROM srv_operations_queue ORDER BY operation LIMIT 500",
        )
        resources = rows(
            connection,
            "SELECT resource_id, COALESCE(MAX(equipment_name), resource_id) AS label "
            "FROM srv_operations_queue WHERE resource_id IS NOT NULL "
            "GROUP BY resource_id ORDER BY label LIMIT 500",
        )
        dates = connection.execute(
            "SELECT MIN(movement_date), MAX(movement_date) FROM srv_operations_queue"
        ).fetchone()
    return {
        "status": "ready",
        "view": view,
        "release": release_payload(snapshot),
        "applicable": ["site", "product", "operation", "resource", "date_from", "date_to"],
        "dataset_applicability": DATASET_FILTERS,
        "options": {
            "site": [option(row["site_code"], row["label"]) for row in sites],
            "product": [
                option(row["product_number"], row["label"])
                for row in products
            ],
            "operation": [
                option(row["operation"], f"Operation {row['operation']}") for row in operations
            ],
            "resource": [
                option(row["resource_id"], row["label"])
                for row in resources
            ],
        },
        "date_range": {"minimum": dates[0], "maximum": dates[1], "grain": "DAY"},
    }


def dashboard_payload(view: View, filters: FlowFilters) -> dict[str, Any]:
    query_specs = {
        "wip": (
            "srv_operations_wip",
            {"site": "site_code", "product": "product_number", "operation": "current_operation", "resource": "resource_id"},
            "wip_quantity_ea DESC",
        ),
        "queue": (
            "srv_operations_queue",
            {"site": "site_code", "operation": "operation", "resource": "resource_id", "date_from": "movement_date", "date_to": "movement_date"},
            "movement_date, site_code, operation",
        ),
        "cycle_time": (
            "srv_operations_cycle_time",
            {"site": "site_code", "product": "product_number", "date_from": "release_date", "date_to": "release_date"},
            "release_date, site_code, product_number",
        ),
        "throughput": (
            "srv_operations_throughput",
            {"site": "site_code", "operation": "operation", "resource": "resource_id", "date_from": "movement_date", "date_to": "movement_date"},
            "movement_date, site_code, operation",
        ),
        "rework": (
            "srv_operations_rework",
            {"site": "site_code", "product": "product_number", "operation": "operation", "date_from": "movement_date", "date_to": "movement_date"},
            "movement_date, site_code, operation",
        ),
        "route_adherence": (
            "srv_operations_route_adherence",
            {"site": "site_code", "product": "product_number"},
            "site_code, product_number, work_order_id, lot_id",
        ),
        "schedule_attainment": (
            "srv_operations_schedule_attainment",
            {"site": "site_code", "product": "product_number", "date_from": "schedule_date", "date_to": "schedule_date"},
            "schedule_date, site_code, product_number",
        ),
        "bottleneck_movement": (
            "srv_operations_bottleneck_movement",
            {"site": "site_code", "operation": "operation", "resource": "resource_id", "date_from": "movement_date", "date_to": "movement_date"},
            "movement_date, site_code",
        ),
        "route_flow": (
            "srv_operations_route_flow",
            {
                "site": "site_code",
                "product": "product_number",
                "operation": "to_operation",
                "resource": "resource_id",
                "date_from": "movement_date",
                "date_to": "movement_date",
            },
            "movement_date, site_code, from_operation, to_operation",
        ),
    }
    data: dict[str, list[dict[str, Any]]] = {}
    with serving_connection(REQUIRED) as (connection, snapshot):
        for name, (table, mapping, order) in query_specs.items():
            where, params = _predicate(filters, mapping)
            limit = MAX_POINTS if name in {
                "queue", "cycle_time", "throughput", "rework",
                "schedule_attainment", "bottleneck_movement",
                "route_flow",
            } else MAX_ROWS
            data[name] = rows(
                connection,
                f'SELECT * FROM "{table}" WHERE {where} ORDER BY {order} LIMIT {limit}',
                params,
            )
    wip = sum(float(row["wip_quantity_ea"] or 0) for row in data["wip"])
    throughput = sum(float(row["throughput_quantity_ea"] or 0) for row in data["throughput"])
    movement_count = sum(int(row["movement_count"] or 0) for row in data["rework"])
    rework_count = sum(int(row["rework_count"] or 0) for row in data["rework"])
    route_lots = len(data["route_adherence"])
    adherent_lots = sum(bool(row["route_adherent"]) for row in data["route_adherence"])
    scheduled = sum(int(row["scheduled_work_order_count"] or 0) for row in data["schedule_attainment"])
    attained = sum(int(row["attained_work_order_count"] or 0) for row in data["schedule_attainment"])
    queue_p90 = [float(row["p90_queue_age_minutes"]) for row in data["queue"] if row["p90_queue_age_minutes"] is not None]
    center = statistics.fmean(queue_p90) if queue_p90 else None
    sigma = statistics.pstdev(queue_p90) if len(queue_p90) >= 2 else None
    return {
        "status": "ready" if any(data.values()) else "empty",
        "message": None if any(data.values()) else "No operations data matches the selected filters.",
        "view": view,
        "release": release_payload(snapshot),
        "filters": filters.model_dump(mode="json"),
        "grain": "DAY",
        "kpis": {
            "wip_quantity_ea": wip,
            "maximum_queue_age_minutes": max(
                (float(row["maximum_queue_age_minutes"] or 0) for row in data["queue"]),
                default=0,
            ),
            "throughput_quantity_ea": throughput,
            "rework_rate_pct": rework_count / movement_count if movement_count else None,
            "route_adherence_pct": adherent_lots / route_lots if route_lots else None,
            "schedule_attainment_pct": attained / scheduled if scheduled else None,
        },
        **data,
        "queue_control_chart": {
            "method": "descriptive mean plus or minus three population standard deviations",
            "center_line_minutes": center,
            "upper_control_limit_minutes": center + 3 * sigma if sigma is not None else None,
            "lower_control_limit_minutes": max(0, center - 3 * sigma) if sigma is not None else None,
            "qualified": len(queue_p90) >= 2,
        },
        "sankey": {
            "available": bool(data["route_flow"]),
            "reason": (
                "Published lot route movement quantities."
                if data["route_flow"]
                else "No route movement records match the selected filters."
            ),
            "rows": data["route_flow"],
        },
        "dataset_applicability": DATASET_FILTERS,
        "limits": {"chart_points": MAX_POINTS, "table_rows": MAX_ROWS},
    }
