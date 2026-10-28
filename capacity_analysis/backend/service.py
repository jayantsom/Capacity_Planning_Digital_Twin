"""Release-pinned, read-only Capacity Analysis queries."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from capacity_analysis.backend.models import (
    AnalysisTab,
    CapacityFilters,
    reconcile_capacity_waterfall,
)
from capacity_twin_core.runtime.database_paths import (
    get_release_pointer,
    get_runtime_home,
    load_app_config,
)

CONFIG = load_app_config("capacity_analysis")
REQUIRED_TABLES = frozenset(CONFIG["query"]["required_serving_tables"])
MAX_POINTS = int(CONFIG["query"]["maximum_chart_points"])
MAX_ROWS = int(CONFIG["query"]["maximum_table_rows"])
SEVERITY_SCORE = {
    "CRITICAL": 6,
    "HIGH": 5,
    "MEDIUM": 4,
    "LOW": 3,
    "BALANCED": 2,
    "EXCESS": 1,
}


class CapacityNotReadyError(RuntimeError):
    """The compatible Serving publication is not ready."""


def _release_snapshot() -> dict[str, Any]:
    """Capture one immutable Serving path from the compatible release pointer."""
    runtime = get_runtime_home().resolve()
    pointer_path = get_release_pointer(runtime)
    if not pointer_path.is_file():
        raise CapacityNotReadyError(
            "Capacity Analysis is not ready. No compatible release is promoted."
        )
    try:
        release = json.loads(pointer_path.read_text(encoding="utf-8"))
        serving_details = release["publications"]["serving"]
        candidate = Path(serving_details["path"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise CapacityNotReadyError(
            "Capacity Analysis is not ready. The release pointer is invalid."
        ) from error
    serving_path = candidate if candidate.is_absolute() else runtime / candidate
    serving_path = serving_path.resolve()
    if runtime != serving_path and runtime not in serving_path.parents:
        raise CapacityNotReadyError("The promoted Serving path escapes the runtime home.")
    if not serving_path.is_file():
        raise CapacityNotReadyError("The promoted Serving database is missing.")
    return {
        "release_id": (
            release.get("release_id")
            or release.get("run_id")
            or serving_details.get("run_id")
        ),
        "published_at": release.get("promoted_at") or release.get("created_at"),
        "serving_run_id": serving_details.get("run_id"),
        "serving_path": serving_path,
    }


@contextmanager
def _serving_connection() -> Iterator[tuple[duckdb.DuckDBPyConnection, dict[str, Any]]]:
    """Open the captured Serving database directly and read-only."""
    snapshot = _release_snapshot()
    connection = duckdb.connect(str(snapshot["serving_path"]), read_only=True)
    try:
        objects = {
            row[0]: row[1]
            for row in connection.execute(
                """
                SELECT table_name, table_type
                FROM information_schema.tables
                WHERE table_schema = 'main'
                """
            ).fetchall()
        }
        missing = sorted(REQUIRED_TABLES - objects.keys())
        non_tables = sorted(
            name for name in REQUIRED_TABLES if objects.get(name) != "BASE TABLE"
        )
        if missing or non_tables:
            detail = []
            if missing:
                detail.append(f"missing {', '.join(missing)}")
            if non_tables:
                detail.append(f"not materialized {', '.join(non_tables)}")
            raise CapacityNotReadyError(
                "Capacity Analysis Serving contract is not ready: " + "; ".join(detail)
            )
        yield connection, snapshot
    except duckdb.Error as error:
        raise CapacityNotReadyError(
            "The promoted Serving database could not be read."
        ) from error
    finally:
        connection.close()


def _rows(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> list[dict[str, Any]]:
    relation = connection.execute(sql, params or [])
    columns = [description[0] for description in relation.description]
    return [
        {
            column: float(value) if isinstance(value, Decimal) else value
            for column, value in zip(columns, row)
        }
        for row in relation.fetchall()
    ]


def _option(value: Any, label: Any) -> dict[str, str]:
    code = str(value)
    full_label = str(label or code)
    return {
        "value": code,
        "code": code,
        "label": full_label if code in full_label else f"{full_label} ({code})",
    }


def _predicates(
    filters: CapacityFilters,
    *,
    alias: str = "",
    include_mode: bool = True,
    include_retest: bool = True,
    include_planning: bool = True,
    include_product: bool = True,
) -> tuple[str, list[Any]]:
    prefix = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: list[Any] = []
    fields = (
        ("site_code", filters.site),
        ("product_number", filters.product if include_product else None),
        ("test_type", filters.test_type),
        ("capacity_mode", filters.capacity_mode if include_mode else None),
        ("retest_type", filters.retest if include_retest else None),
        (
            "planning_version_id",
            filters.planning_version if include_planning else None,
        ),
    )
    for column, value in fields:
        if value not in (None, ""):
            clauses.append(f"{prefix}{column} = ?")
            params.append(value)
    if filters.month_from is not None:
        clauses.append(f"CAST({prefix}month_key AS INTEGER) >= ?")
        params.append(filters.month_from)
    if filters.month_to is not None:
        clauses.append(f"CAST({prefix}month_key AS INTEGER) <= ?")
        params.append(filters.month_to)
    return (" AND ".join(clauses) if clauses else "TRUE"), params


def _metadata(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, dict[str, str]]:
    sites = {
        str(row["site_code"]): str(row["site_name"] or row["site_code"])
        for row in _rows(
            connection,
            """
            SELECT site_code, MAX(site_name) AS site_name
            FROM srv_vw_capacity_summary
            GROUP BY site_code
            """,
        )
    }
    products = {
        str(row["product_number"]): str(
            row["product_description"] or row["product_number"]
        )
        for row in _rows(
            connection,
            """
            SELECT product_number, MAX(product_description) AS product_description
            FROM srv_vw_capacity_summary
            GROUP BY product_number
            """,
        )
    }
    tests = {
        str(row["test_type"]): str(row["test_type_name"] or row["test_type"])
        for row in _rows(
            connection,
            """
            SELECT test_type, MAX(test_category_name) AS test_type_name
            FROM srv_gcm_resource_contract
            GROUP BY test_type
            """,
        )
    }
    return {"sites": sites, "products": products, "tests": tests}


def health_payload() -> dict[str, Any]:
    """Report release and materialized Serving readiness without changing runtime."""
    try:
        with _serving_connection() as (connection, snapshot):
            counts = {
                name: int(
                    connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                )
                for name in sorted(REQUIRED_TABLES)
            }
    except CapacityNotReadyError as error:
        return {
            "status": "not-ready",
            "reason": str(error),
            "release_id": None,
            "tables": {},
        }
    return {
        "status": "ready",
        "release_id": snapshot["release_id"],
        "serving_run_id": snapshot["serving_run_id"],
        "published_at": snapshot["published_at"],
        "tables": counts,
    }


def filter_payload(tab: AnalysisTab) -> dict[str, Any]:
    """Declare applicable filters and full labels from the pinned Serving release."""
    with _serving_connection() as (connection, snapshot):
        labels = _metadata(connection)
        versions = _rows(
            connection,
            """
            SELECT planning_version_id, MAX(plan_as_of_date) AS plan_as_of_date
            FROM srv_vw_capacity_summary
            GROUP BY planning_version_id
            ORDER BY plan_as_of_date DESC, planning_version_id
            LIMIT 200
            """,
        )
        months = connection.execute(
            """
            SELECT MIN(CAST(month_key AS INTEGER)), MAX(CAST(month_key AS INTEGER))
            FROM srv_vw_capacity_summary
            """
        ).fetchone()
    return {
        "status": "ready",
        "tab": tab,
        "release_id": snapshot["release_id"],
        "applicable": [
            "site",
            "product",
            "test_type",
            "capacity_mode",
            "retest",
            "planning_version",
            "month_from",
            "month_to",
        ],
        "options": {
            "site": [
                _option(code, name) for code, name in sorted(labels["sites"].items())
            ],
            "product": [
                _option(code, name)
                for code, name in sorted(labels["products"].items())
            ],
            "test_type": [
                _option(code, name) for code, name in sorted(labels["tests"].items())
            ],
            "capacity_mode": [
                _option("NORMAL", "Normal Capacity"),
                _option("MAXIMUM", "Maximum Capacity"),
            ],
            "retest": [
                _option("NONE", "No Retest"),
                _option("TYPE1", "Standard / Type 1"),
                _option("TYPE2", "Measured / Type 2"),
            ],
            "planning_version": [
                _option(
                    row["planning_version_id"],
                    (
                        f"Plan as of {row['plan_as_of_date']}"
                        if row["plan_as_of_date"]
                        else "Planning version"
                    ),
                )
                for row in versions
            ],
        },
        "month_range": {
            "minimum": months[0],
            "maximum": months[1],
            "grain": "MONTH",
        },
    }


def _trend(
    connection: duckdb.DuckDBPyConnection,
    filters: CapacityFilters,
) -> list[dict[str, Any]]:
    where, params = _predicates(filters, include_mode=False)
    planned = _rows(
        connection,
        f"""
        SELECT
            CAST(month_key AS INTEGER) AS month,
            SUM(CASE WHEN capacity_mode = 'NORMAL' THEN demand_qty ELSE 0 END)
                AS demand,
            SUM(CASE WHEN capacity_mode = 'NORMAL' THEN capacity_qty ELSE 0 END)
                AS normal_capacity,
            SUM(CASE WHEN capacity_mode = 'MAXIMUM' THEN capacity_qty ELSE 0 END)
                AS maximum_capacity
        FROM srv_vw_capacity_summary
        WHERE {where}
        GROUP BY month_key
        ORDER BY month_key
        LIMIT {MAX_POINTS}
        """,
        params,
    )
    actual_where, actual_params = _predicates(
        filters,
        include_mode=False,
        include_retest=False,
        include_planning=False,
    )
    actual = {
        int(row["month"]): float(row["actual_output"] or 0)
        for row in _rows(
            connection,
            f"""
            SELECT CAST(month_key AS INTEGER) AS month,
                   SUM(actual_passed_qty) AS actual_output
            FROM srv_actual_output
            WHERE {actual_where}
            GROUP BY month_key
            ORDER BY month_key
            LIMIT {MAX_POINTS}
            """,
            actual_params,
        )
    }
    demonstrated = {
        int(row["month"]): float(row["demonstrated_capacity"] or 0)
        for row in _rows(
            connection,
            f"""
            SELECT CAST(month_key AS INTEGER) AS month,
                   SUM(demonstrated_capacity_qty) AS demonstrated_capacity
            FROM srv_demonstrated_capacity
            WHERE {actual_where}
            GROUP BY month_key
            ORDER BY month_key
            LIMIT {MAX_POINTS}
            """,
            actual_params,
        )
    }
    return [
        {
            **row,
            "actual_output": actual.get(int(row["month"])),
            "demonstrated_capacity": demonstrated.get(int(row["month"])),
        }
        for row in planned
    ]


def _alternatives(
    connection: duckdb.DuckDBPyConnection,
    filters: CapacityFilters,
    labels: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    where, params = _predicates(
        filters,
        include_mode=False,
        include_retest=False,
    )
    rows = _rows(
        connection,
        f"""
        SELECT
            site_code,
            product_number,
            test_type,
            COALESCE(pool_id, route_step_id) AS alternative_group,
            MAX(resource_behavior) AS resource_behavior,
            string_agg(DISTINCT equipment_id, ', ' ORDER BY equipment_id)
                AS qualified_resources,
            string_agg(DISTINCT qualification_id, ', ' ORDER BY qualification_id)
                AS qualification_evidence,
            COUNT(DISTINCT equipment_id) AS alternative_count
        FROM srv_gcm_resource_contract
        WHERE {where}
          AND resource_behavior IN ('ALTERNATIVE_POOL', 'SHARED_POOL')
        GROUP BY site_code, product_number, test_type,
                 COALESCE(pool_id, route_step_id)
        ORDER BY alternative_count DESC, site_code, product_number
        LIMIT {MAX_ROWS}
        """,
        params,
    )
    for row in rows:
        row["site_label"] = labels["sites"].get(str(row["site_code"]), row["site_code"])
        row["product_label"] = labels["products"].get(
            str(row["product_number"]), row["product_number"]
        )
        row["test_type_label"] = labels["tests"].get(
            str(row["test_type"]), row["test_type"]
        )
    return rows


def tactical_payload(filters: CapacityFilters) -> dict[str, Any]:
    """Return all bounded Tactical Capacity sections from Serving only."""
    with _serving_connection() as (connection, snapshot):
        labels = _metadata(connection)
        trend = _trend(connection, filters)
        where, params = _predicates(filters)
        heatmap = _rows(
            connection,
            f"""
            SELECT site_code, MAX(site_name) AS site_name, test_type,
                   SUM(gap_qty) AS gap_qty, SUM(demand_qty) AS demand_qty,
                   SUM(capacity_qty) AS capacity_qty
            FROM srv_vw_capacity_summary
            WHERE {where}
            GROUP BY site_code, test_type
            ORDER BY gap_qty, site_code, test_type
            LIMIT {MAX_POINTS}
            """,
            params,
        )
        equipment = _rows(
            connection,
            f"""
            SELECT site_code, MAX(site_name) AS site_name, test_type,
                   equipment_type,
                   SUM(demand_qty) AS demand_qty,
                   SUM(capacity_qty) AS capacity_qty,
                   SUM(investment_need_units) AS required_additional_units,
                   SUM(excess_capacity_units) AS excess_units
            FROM srv_vw_capacity_summary
            WHERE {where}
            GROUP BY site_code, test_type, equipment_type
            ORDER BY required_additional_units DESC, site_code, test_type
            LIMIT {MAX_ROWS}
            """,
            params,
        )
        rank_where, rank_params = _predicates(
            filters,
        )
        ranking = _rows(
            connection,
            f"""
            SELECT site_code, test_type, resource_constraint_id,
                   MAX(resource_behavior) AS resource_behavior,
                   SUM(required_resource_hours) AS required_resource_hours,
                   SUM(available_resource_hours) AS available_resource_hours,
                   SUM(gap_resource_hours) AS gap_resource_hours,
                   MAX(affected_products) AS affected_products,
                   MIN(gap_ratio) AS gap_ratio,
                   MAX(bottleneck_severity) AS severity
            FROM srv_resource_constraints
            WHERE {rank_where}
            GROUP BY site_code, test_type, resource_constraint_id
            ORDER BY gap_ratio, required_resource_hours DESC
            LIMIT {MAX_ROWS}
            """,
            rank_params,
        )
        alternatives = _alternatives(connection, filters, labels)

    for row in heatmap + equipment + ranking:
        row["site_label"] = labels["sites"].get(str(row["site_code"]), row["site_code"])
        row["test_type_label"] = labels["tests"].get(
            str(row["test_type"]), row["test_type"]
        )
    total_demand = sum(float(row["demand"] or 0) for row in trend)
    total_normal = sum(float(row["normal_capacity"] or 0) for row in trend)
    total_maximum = sum(float(row["maximum_capacity"] or 0) for row in trend)
    total_actual = sum(float(row["actual_output"] or 0) for row in trend)
    total_demonstrated = sum(
        float(row["demonstrated_capacity"] or 0) for row in trend
    )
    selected_capacity = (
        total_normal if filters.capacity_mode == "NORMAL" else total_maximum
    )
    status = "ready" if trend else "empty"
    return {
        "status": status,
        "message": (
            None
            if trend
            else "No Tactical Capacity data matches the selected filters."
        ),
        "release": {
            "release_id": snapshot["release_id"],
            "serving_run_id": snapshot["serving_run_id"],
            "published_at": snapshot["published_at"],
        },
        "filters": filters.model_dump(),
        "grain": "MONTH",
        "unit": "EA",
        "kpis": {
            "demand": total_demand,
            "normal_capacity": total_normal,
            "maximum_capacity": total_maximum,
            "actual_output": total_actual,
            "demonstrated_capacity": total_demonstrated,
            "selected_gap": selected_capacity - total_demand,
            "selected_utilization": (
                total_demand / selected_capacity if selected_capacity else None
            ),
        },
        "trend": trend,
        "capacity_loss_waterfall": reconcile_capacity_waterfall(
            total_maximum,
            total_normal,
        ).model_dump(),
        "site_test_gap_heatmap": heatmap,
        "constrained_resource_ranking": ranking,
        "equipment_requirements": equipment,
        "alternative_resources": alternatives,
        "limits": {"chart_points": MAX_POINTS, "table_rows": MAX_ROWS},
    }


def bottleneck_payload(filters: CapacityFilters) -> dict[str, Any]:
    """Return resource-hour bottlenecks, movement, impact, and investment need."""
    with _serving_connection() as (connection, snapshot):
        labels = _metadata(connection)
        where, params = _predicates(filters)
        constraints = _rows(
            connection,
            f"""
            SELECT
                CAST(month_key AS INTEGER) AS month,
                site_code,
                test_type,
                resource_constraint_id,
                resource_behavior,
                equipment_id,
                equipment_type,
                affected_products,
                required_resource_hours,
                available_resource_hours,
                gap_resource_hours,
                gap_ratio,
                bottleneck_severity
            FROM srv_resource_constraints
            WHERE {where}
            ORDER BY gap_ratio, month_key, resource_constraint_id
            LIMIT {MAX_ROWS}
            """,
            params,
        )
        movement = _rows(
            connection,
            f"""
            SELECT
                CAST(month_key AS INTEGER) AS month,
                site_code,
                test_type,
                resource_constraint_id,
                MIN(gap_ratio) AS gap_ratio,
                MIN(gap_resource_hours) AS gap_resource_hours,
                MAX(affected_products) AS affected_products
            FROM srv_resource_constraints
            WHERE {where}
            GROUP BY month_key, site_code, test_type, resource_constraint_id
            ORDER BY month_key, gap_ratio
            LIMIT {MAX_POINTS}
            """,
            params,
        )
        investment = _rows(
            connection,
            f"""
            SELECT site_code, test_type, equipment_type,
                   SUM(investment_need_units) AS investment_need_units,
                   SUM(demand_qty) AS affected_demand_qty,
                   MIN(gap_pct) AS worst_gap_pct
            FROM srv_vw_capacity_summary
            WHERE {where}
            GROUP BY site_code, test_type, equipment_type
            HAVING SUM(investment_need_units) > 0
            ORDER BY investment_need_units DESC
            LIMIT {MAX_ROWS}
            """,
            params,
        )
        alternatives = _alternatives(connection, filters, labels)
    for row in constraints + movement + investment:
        row["site_label"] = labels["sites"].get(str(row["site_code"]), row["site_code"])
        row["test_type_label"] = labels["tests"].get(
            str(row["test_type"]), row["test_type"]
        )
        if "bottleneck_severity" in row:
            row["severity_score"] = SEVERITY_SCORE.get(
                str(row["bottleneck_severity"]), 0
            )
    critical = sum(
        1
        for row in constraints
        if row["bottleneck_severity"] in {"CRITICAL", "HIGH"}
    )
    shortfall_hours = sum(
        abs(min(float(row["gap_resource_hours"] or 0), 0)) for row in constraints
    )
    investment_units = sum(
        math.ceil(float(row["investment_need_units"] or 0))
        for row in investment
    )
    return {
        "status": "ready" if constraints else "empty",
        "message": (
            None
            if constraints
            else "No Bottleneck Analysis data matches the selected filters."
        ),
        "release": {
            "release_id": snapshot["release_id"],
            "serving_run_id": snapshot["serving_run_id"],
            "published_at": snapshot["published_at"],
        },
        "filters": filters.model_dump(),
        "grain": "MONTH",
        "kpis": {
            "high_or_critical_constraints": critical,
            "resource_hour_shortfall": shortfall_hours,
            "affected_products": sum(
                int(row["affected_products"] or 0) for row in constraints
            ),
            "investment_need_units": investment_units,
        },
        "constraints": constraints,
        "movement": movement,
        "investment_need": investment,
        "alternative_resources": alternatives,
        "limits": {"chart_points": MAX_POINTS, "table_rows": MAX_ROWS},
    }
