"""Serving-only NPI readiness and ramp queries."""

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
from npi_ramp_planning.backend.models import NpiFilters

View = Literal["program", "manufacturing", "test", "yield"]
CONFIG = load_app_config("npi_ramp_planning")
REQUIRED = frozenset(CONFIG["query"]["required_serving_tables"])
MAX_POINTS = int(CONFIG["query"]["maximum_chart_points"])
MAX_ROWS = int(CONFIG["query"]["maximum_table_rows"])


def _ramp_where(filters: NpiFilters) -> tuple[str, list[Any]]:
    clauses, params = [], []
    for column, value in (
        ("program_id", filters.program),
        ("site_code", filters.site),
        ("product_number", filters.product),
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


def _readiness_where(filters: NpiFilters) -> tuple[str, list[Any]]:
    clauses, params = [], []
    for column, value in (
        ("program_id", filters.program),
        ("lead_site_code", filters.site),
        ("product_number", filters.product),
    ):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    return " AND ".join(clauses) or "TRUE", params


def health() -> dict[str, Any]:
    return health_payload("npi-ramp-planning", REQUIRED)


def filters_payload(view: View) -> dict[str, Any]:
    with serving_connection(REQUIRED) as (connection, snapshot):
        programs = rows(
            connection,
            "SELECT program_id, MAX(program_name) AS label FROM srv_npi_readiness "
            "GROUP BY program_id ORDER BY label LIMIT 200",
        )
        sites = rows(
            connection,
            "SELECT site_code, MAX(site_name) AS label FROM srv_npi_ramp "
            "GROUP BY site_code ORDER BY label LIMIT 200",
        )
        products = rows(
            connection,
            "SELECT product_number, MAX(product_description) AS label FROM srv_npi_ramp "
            "GROUP BY product_number ORDER BY label LIMIT 500",
        )
        months = connection.execute(
            "SELECT MIN(month_key), MAX(month_key) FROM srv_npi_ramp"
        ).fetchone()
    return {
        "status": "ready",
        "view": view,
        "release": release_payload(snapshot),
        "applicable": ["program", "site", "product", "month_from", "month_to"],
        "options": {
            "program": [option(row["program_id"], row["label"]) for row in programs],
            "site": [option(row["site_code"], row["label"]) for row in sites],
            "product": [
                option(row["product_number"], row["label"])
                for row in products
            ],
        },
        "month_range": {"minimum": months[0], "maximum": months[1], "grain": "MONTH"},
    }


def dashboard_payload(view: View, filters: NpiFilters) -> dict[str, Any]:
    ramp_where, ramp_params = _ramp_where(filters)
    readiness_where, readiness_params = _readiness_where(filters)
    with serving_connection(REQUIRED) as (connection, snapshot):
        readiness = rows(
            connection,
            f"""
            SELECT * FROM srv_npi_readiness WHERE {readiness_where}
            ORDER BY launch_risk_tier DESC, planned_launch_date, program_id
            LIMIT {MAX_ROWS}
            """,
            readiness_params,
        )
        ramp = rows(
            connection,
            f"""
            SELECT program_id, product_number, product_description,
                   site_code, site_name, month_key,
                   target_quantity_ea, actual_quantity_ea, cumulative_quantity_ea,
                   target_yield_pct, actual_yield_pct,
                   ramp_quantity_variance_ea, ramp_yield_variance_pct,
                   target_status, actual_status
            FROM srv_npi_ramp WHERE {ramp_where}
            ORDER BY month_key, program_id, site_code LIMIT {MAX_POINTS}
            """,
            ramp_params,
        )
        monthly = rows(
            connection,
            f"""
            SELECT month_key AS month,
                   SUM(target_quantity_ea) AS target_quantity_ea,
                   SUM(actual_quantity_ea) AS actual_quantity_ea,
                   AVG(target_yield_pct) AS target_yield_pct,
                   AVG(actual_yield_pct) AS actual_yield_pct
            FROM srv_npi_ramp WHERE {ramp_where}
            GROUP BY month_key ORDER BY month_key LIMIT {MAX_POINTS}
            """,
            ramp_params,
        )
        stage_gates = rows(
            connection,
            f"""
            SELECT *
            FROM srv_npi_stage_gate
            WHERE {readiness_where}
            ORDER BY program_id, gate_sequence
            LIMIT {MAX_ROWS}
            """,
            readiness_params,
        )
    program_count = len(readiness)
    target = sum(float(row["target_quantity_ea"] or 0) for row in ramp)
    actual = sum(float(row["actual_quantity_ea"] or 0) for row in ramp)
    learning_rows = [
        row for row in ramp
        if row["cumulative_quantity_ea"] is not None and row["actual_yield_pct"] is not None
    ]
    return {
        "status": "ready" if readiness or ramp else "empty",
        "message": None if readiness or ramp else "No NPI data matches the selected filters.",
        "view": view,
        "release": release_payload(snapshot),
        "filters": filters.model_dump(),
        "grain": "MONTH",
        "kpis": {
            "program_count": program_count,
            "average_readiness_pct": (
                sum(float(row["readiness_score_pct"] or 0) for row in readiness) / program_count
                if program_count else None
            ),
            "high_risk_programs": sum(row["launch_risk_tier"] == "HIGH" for row in readiness),
            "tooling_items_at_risk": sum(
                int(row["tooling_items_at_risk"] or 0) for row in readiness
            ),
            "target_launch_quantity_ea": target,
            "actual_launch_quantity_ea": actual,
            "launch_quantity_variance_ea": actual - target,
        },
        "readiness": readiness,
        "ramp": ramp,
        "monthly_ramp": monthly,
        "learning_curve": {
            "available": len(learning_rows) >= 2,
            "reason": (
                None
                if len(learning_rows) >= 2
                else "Learning curve requires at least two cumulative-production observations."
            ),
            "rows": learning_rows if len(learning_rows) >= 2 else [],
            "x_field": "cumulative_quantity_ea",
            "y_field": "actual_yield_pct",
        },
        "stage_gate_timeline": {
            "available": bool(stage_gates),
            "reason": (
                "Published gate-level planned and actual dates."
                if stage_gates
                else "No stage-gate records match the selected filters."
            ),
            "rows": stage_gates,
        },
        "qualification_matrix": {
            "grain": "NPI program",
            "rows": [
                {
                    "program_id": row["program_id"],
                    "program_name": row["program_name"],
                    "qualification_count": row["qualification_count"],
                    "qualifications_accepted": row["qualifications_accepted"],
                    "pilot_lot_count": row["pilot_lot_count"],
                    "pilot_yield_pct": row["pilot_yield_pct"],
                }
                for row in readiness
            ],
        },
        "limits": {"chart_points": MAX_POINTS, "table_rows": MAX_ROWS},
    }
