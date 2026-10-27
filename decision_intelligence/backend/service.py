"""Read-only dashboard queries and ML job orchestration."""

from __future__ import annotations

import json
from calendar import monthrange
from datetime import date
from typing import Any

import duckdb

from capacity_twin_core.comparison import get_comparison_window, window_predicate
from capacity_twin_core.runtime.database_paths import get_runtime_home
from decision_intelligence.ml.run_ml import (
    REQUIRED_OUTPUT_TABLES,
    WORKFLOWS,
    run_ml_pipeline,
)
from decision_intelligence.ml_support import (
    file_sha256,
    published_database_path,
    source_database_path,
)

WORKFLOW_KEYS = {
    "demand": 1,
    "yield": 2,
    "oee-risk": 3,
    "oee-anomaly": 4,
    "capex": 5,
}

WORKFLOW_FILTERS = {
    "demand": {"site", "product", "month_from", "month_to"},
    "yield": {
        "site",
        "product",
        "test_type",
        "planning_version",
        "grain",
        "month_from",
        "month_to",
    },
    "oee-risk": {"site", "test_type", "machine", "grain", "month_from", "month_to"},
    "oee-anomaly": {"site", "test_type", "machine", "grain", "month_from", "month_to"},
    "capex": {"site", "test_type"},
}

WORKFLOW_DIMENSIONS = {
    "demand": (
        "gold_demand_forecast",
        {"site": "site_id", "product": "product_id"},
    ),
    "yield": (
        "gold_yield_predictions",
        {
            "site": "site_id",
            "product": "product_id",
            "test_type": "test_type_id",
            "planning_version": "planning_version_id",
        },
    ),
    "oee-risk": (
        "gold_maintenance_risk",
        {"site": "site_id", "test_type": "test_type_id", "machine": "equipment_id"},
    ),
    "oee-anomaly": (
        "gold_oee_anomalies",
        {"site": "site_id", "test_type": "test_type_id", "machine": "equipment_id"},
    ),
    "capex": (
        "gold_capex_mc_summary",
        {"site": "site_code", "test_type": "test_type"},
    ),
}

DIMENSION_LABELS = {
    "site": (
        "slvr_ref_site",
        "site_code",
        "site_name || ' (' || site_code || ')'",
    ),
    "product": (
        "slvr_prod_master",
        "product_number",
        "product_description || ' (' || product_number || ')'",
    ),
    "test_type": (
        "slvr_ref_test_type",
        "test_type",
        "test_category_name || ' (' || test_type || ')'",
    ),
    "machine": (
        "slvr_ref_equipment",
        "equipment_id",
        "equipment_name || ' (' || equipment_id || ')'",
    ),
}

WORKFLOW_METADATA = [
    {
        "key": "demand",
        "priority": 1,
        "name": "Demand Forecasting",
        "subtitle": "18-MONTH FORECAST · TEMPORAL HOLDOUT",
    },
    {
        "key": "yield",
        "priority": 2,
        "name": "Yield Prediction",
        "subtitle": "MEASURED YIELD · SHAP DRIVERS",
    },
    {
        "key": "oee-risk",
        "priority": 3,
        "name": "OEE Degradation Risk",
        "subtitle": "RISK SIGNAL · NOT FAILURE PREDICTION",
    },
    {
        "key": "oee-anomaly",
        "priority": 4,
        "name": "OEE Anomaly",
        "subtitle": "HISTORICAL THRESHOLDS · DRIVER",
    },
    {
        "key": "capex",
        "priority": 5,
        "name": "CapEx Simulation",
        "subtitle": "P50 · P80 · P95 · NOT OPTIMIZATION",
    },
]


def publication_payload() -> dict[str, Any]:
    """Return safe provenance for the currently promoted ML run."""
    runtime = get_runtime_home().resolve()
    pointer_path = runtime / "ml_current.json"
    if not pointer_path.is_file():
        raise FileNotFoundError("No ML publication")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    manifest_path = (runtime / pointer["manifest"]).resolve()
    if runtime not in manifest_path.parents:
        raise ValueError("ML publication pointer escapes the runtime home")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "run_id": manifest.get("run_id"),
        "created_at": manifest.get("created_at"),
        "database_sha256": manifest.get("database_sha256"),
        "source_database_sha256": manifest.get("source_database_sha256"),
        "workflow_results": manifest.get("workflow_results", {}),
        "output_tables": sorted(manifest.get("output_schema", {})),
    }


def health_payload() -> dict[str, Any]:
    """Report publication completeness and source freshness."""
    runtime = get_runtime_home()
    pointer_path = runtime / "ml_current.json"
    if not pointer_path.is_file():
        return {
            "status": "degraded",
            "reason": "No ML publication",
            "run_id": None,
            "stale": True,
            "workflow_count": len(WORKFLOWS),
        }
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        database = published_database_path()
        manifest_path = (runtime / pointer["manifest"]).resolve()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        with duckdb.connect(str(database), read_only=True) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM information_schema.tables"
                ).fetchall()
            }
    except (OSError, json.JSONDecodeError, KeyError, ValueError, duckdb.Error) as error:
        return {
            "status": "degraded",
            "reason": f"ML publication is unreadable: {type(error).__name__}",
            "run_id": None,
            "stale": True,
            "workflow_count": len(WORKFLOWS),
        }
    missing = sorted(REQUIRED_OUTPUT_TABLES - tables)
    source = source_database_path()
    stale = (
        not source.is_file()
        or manifest.get("source_database_sha256") != file_sha256(source)
    )
    return {
        "status": "ready" if not missing else "degraded",
        "run_id": pointer.get("run_id"),
        "created_at": manifest.get("created_at"),
        "stale": stale,
        "missing_outputs": missing,
        "workflow_count": len(WORKFLOWS),
    }


def filter_metadata(
    workflow: str,
    selected: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Return human-readable options and explicit filter applicability."""
    if workflow not in WORKFLOW_FILTERS:
        raise KeyError(workflow)
    database = published_database_path()
    if not database.is_file():
        raise FileNotFoundError("No ML publication. Run the ML workflows first.")
    table, dimensions = WORKFLOW_DIMENSIONS[workflow]
    selected = selected or {}
    options: dict[str, list[dict]] = {
        "site": [],
        "product": [],
        "test_type": [],
        "machine": [],
        "planning_version": [],
    }
    with duckdb.connect(str(database), read_only=True) as connection:
        for dimension, column in dimensions.items():
            clauses = []
            parameters = []
            for other_dimension, other_column in dimensions.items():
                value = selected.get(other_dimension)
                if other_dimension != dimension and value:
                    clauses.append(f'base."{other_column}" = ?')
                    parameters.append(value)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            if dimension == "planning_version":
                sql = f"""
                    SELECT DISTINCT base."{column}" AS value,
                                    base."{column}" AS label
                    FROM {table} AS base
                    {where}
                    ORDER BY label
                """
            else:
                reference, reference_key, label_expression = DIMENSION_LABELS[dimension]
                sql = f"""
                    SELECT DISTINCT base."{column}" AS value,
                           COALESCE(ref.label, CAST(base."{column}" AS VARCHAR)) AS label
                    FROM {table} AS base
                    LEFT JOIN (
                        SELECT "{reference_key}" AS reference_value,
                               {label_expression} AS label
                        FROM {reference}
                    ) AS ref ON base."{column}" = ref.reference_value
                    {where}
                    ORDER BY label
                """
            options[dimension] = _rows(connection, sql, parameters)
    return {
        "workflow": workflow,
        "applicable_filters": sorted(WORKFLOW_FILTERS[workflow]),
        "options": options,
    }


def dashboard(
    workflow: str,
    *,
    site: str | None = None,
    product: str | None = None,
    test_type: str | None = None,
    machine: str | None = None,
    planning_version: str | None = None,
    grain: str | None = None,
    window: str = "total",
    month_from: int | None = None,
    month_to: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return one allowlisted dashboard payload."""
    if workflow not in WORKFLOW_KEYS:
        raise KeyError(workflow)
    filters = {
        "workflow": workflow,
        "site": site,
        "product": product,
        "test_type": test_type,
        "machine": machine,
        "planning_version": planning_version,
        "grain": grain or "MONTH",
        "comparison_window": get_comparison_window(window),
        "month_from": month_from,
        "month_to": month_to,
    }
    database = published_database_path()
    if not database.is_file():
        raise FileNotFoundError("No ML publication. Run the ML workflows first.")
    with duckdb.connect(str(database), read_only=True) as connection:
        if workflow == "demand":
            return _demand_dashboard(connection, filters, limit)
        if workflow == "yield":
            return _yield_dashboard(connection, filters, limit)
        if workflow == "oee-risk":
            return _risk_dashboard(connection, filters, limit)
        if workflow == "oee-anomaly":
            return _anomaly_dashboard(connection, filters, limit)
        return _capex_dashboard(connection, filters, limit)


def run_workflows(priorities: list[int] | None, report) -> dict[str, Any]:
    """Run selected workflows through the atomic publication gate."""
    selected = priorities or list(WORKFLOWS)
    if sorted(set(selected) - set(WORKFLOWS)):
        raise ValueError("Workflow priorities must be between 1 and 5")
    results = run_ml_pipeline(selected, progress_callback=report)
    statuses = {result["status"] for result in results.values()}
    if "ERROR" in statuses:
        job_status = "FAILED"
        detail = "One or more workflows failed; the prior publication remains active"
    elif "NOT_EVALUABLE" in statuses:
        job_status = "NOT_EVALUABLE"
        detail = "One or more workflows lacked sufficient evaluable data"
    else:
        job_status = "COMPLETED"
        detail = "Requested workflows published successfully"
    return {
        "job_status": job_status,
        "job_detail": detail,
        "priorities": selected,
        "results": results,
    }


def _where(connection, table: str, filters: dict[str, Any]) -> tuple[str, list[Any]]:
    columns = {
        row[0] for row in connection.execute(f'DESCRIBE "{table}"').fetchall()
    }
    choices = {
        "site": ("site_id", "site_code"),
        "product": ("product_id", "product_number"),
        "test_type": ("test_type_id", "test_type"),
        "planning_version": ("planning_version_id",),
        "machine": ("equipment_id", "machine_id"),
    }
    clauses: list[str] = []
    parameters: list[Any] = []
    for filter_name, candidates in choices.items():
        value = filters.get(filter_name)
        column = next((candidate for candidate in candidates if candidate in columns), None)
        if value and column:
            clauses.append(f'"{column}" = ?')
            parameters.append(value)
    month_column = next(
        (
            column
            for column in ("month", "month_key", "forecast_month_key")
            if column in columns
        ),
        None,
    )
    if month_column and filters.get("month_from"):
        clauses.append(f'"{month_column}" >= ?')
        parameters.append(filters["month_from"])
    if month_column and filters.get("month_to"):
        clauses.append(f'"{month_column}" <= ?')
        parameters.append(filters["month_to"])
    comparison_window = filters.get("comparison_window")
    if month_column and comparison_window:
        clause, values = window_predicate(
            comparison_window,
            month_column,
            "month_key",
        )
        if clause:
            clauses.append(clause)
            parameters.extend(values)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), parameters


def _rows(connection, sql: str, parameters: list[Any] | None = None) -> list[dict]:
    frame = connection.execute(sql, parameters or []).df()
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _scalar(connection, sql: str, parameters: list[Any] | None = None) -> Any:
    value = connection.execute(sql, parameters or []).fetchone()[0]
    return value.item() if hasattr(value, "item") else value


def _operational_panel(connection, filters: dict[str, Any]) -> dict[str, Any]:
    """Return recomputed weekly/monthly execution metrics, never ML predictions."""
    grain = filters.get("grain", "MONTH")
    clauses = ["period_grain = ?"]
    parameters: list[Any] = [grain]
    for filter_name, column in (
        ("site", "site_code"),
        ("product", "product_number"),
        ("test_type", "test_type"),
    ):
        value = filters.get(filter_name)
        if value:
            clauses.append(f'"{column}" = ?')
            parameters.append(value)
    window = filters["comparison_window"]
    selected_start = window.start_date
    selected_end = window.end_date
    if window.window_id != "total":
        clauses.extend(["period_end >= ?", "period_start <= ?"])
        parameters.extend([selected_start.isoformat(), selected_end.isoformat()])
    elif filters.get("month_from"):
        value = int(filters["month_from"])
        selected_start = date(value // 100, value % 100, 1)
        clauses.append("period_end >= ?")
        parameters.append(selected_start.isoformat())
    if window.window_id == "total" and filters.get("month_to"):
        value = int(filters["month_to"])
        selected_end = date(
            value // 100,
            value % 100,
            monthrange(value // 100, value % 100)[1],
        )
        clauses.append("period_start <= ?")
        parameters.append(selected_end.isoformat())
    where = " WHERE " + " AND ".join(clauses)
    rows = _rows(
        connection,
        f"""
        WITH performance AS (
            SELECT period_key, MIN(period_start) AS period_start,
                   MAX(period_end) AS period_end,
                   BOOL_AND(period_complete) AS source_period_complete,
                   SUM(passed_qty) AS passed_qty,
                   SUM(tested_qty) AS tested_qty,
                   SUM(observation_rows) AS observation_rows,
                   SUM(downtime_seconds) AS downtime_seconds,
                   SUM(productive_seconds) AS productive_seconds
            FROM gold_operational_performance
            {where}
            GROUP BY period_key
        ),
        events AS (
            SELECT period_key, SUM(event_count) AS event_count
            FROM gold_operational_events
            {where}
            GROUP BY period_key
        ),
        rates AS (
            SELECT
                performance.*,
                LEAST(
                    1.0,
                    GREATEST(
                        0.0,
                        1.0 - downtime_seconds
                            / NULLIF(observation_rows * 8.0 * 3600.0, 0)
                    )
                ) AS availability_pct,
                LEAST(
                    1.0,
                    GREATEST(
                        0.0,
                        productive_seconds
                            / NULLIF(
                                observation_rows * 8.0 * 3600.0 - downtime_seconds,
                                0
                            )
                    )
                ) AS performance_pct,
                LEAST(1.0, GREATEST(0.0, passed_qty / NULLIF(tested_qty, 0)))
                    AS quality_pct
            FROM performance
        )
        SELECT
            rates.period_key AS period,
            rates.period_start,
            rates.period_end,
            rates.source_period_complete,
            100 * rates.quality_pct AS yield_pct,
            100 * LEAST(
                1.0,
                GREATEST(
                    0.0,
                    rates.availability_pct * rates.performance_pct * rates.quality_pct
                )
            ) AS oee_pct,
            rates.downtime_seconds / 3600.0 AS downtime_hours,
            rates.tested_qty
                / NULLIF(
                    (rates.observation_rows * 8.0 * 3600.0 - rates.downtime_seconds)
                    / 3600.0,
                    0
                ) AS throughput_uph,
            COALESCE(events.event_count, 0) AS event_count
        FROM rates
        LEFT JOIN events USING (period_key)
        ORDER BY rates.period_key
        """,
        [*parameters, *parameters],
    )
    for row in rows:
        period_start = date.fromisoformat(str(row["period_start"])[:10])
        period_end = date.fromisoformat(str(row["period_end"])[:10])
        row["partial_period"] = (
            not row["source_period_complete"]
            or (selected_start is not None and period_start < selected_start)
            or (selected_end is not None and period_end > selected_end)
        )
    return {
        "title": (
            "Operational Yield"
            if filters.get("workflow") == "yield"
            else "Operational Performance"
        ),
        "grain": grain,
        "native_grain": "DAY",
        "supported_grains": ["WEEK", "MONTH"],
        "source_table": "gold_operational_performance",
        "rows": rows,
        "filter_scope": {
            "applied": [
                name
                for name in ("site", "product", "test_type")
                if filters.get(name)
            ],
            "not_applicable": ["machine"] if filters.get("machine") else [],
        },
    }


def _demand_dashboard(connection, filters, limit) -> dict[str, Any]:
    where, params = _where(connection, "gold_demand_forecast", filters)
    accuracy_where, accuracy_params = _where(
        connection, "gold_forecast_accuracy_ml", filters
    )
    feature_where, feature_params = _where(
        connection, "gold_ml_feature_store", filters
    )
    kpis = {
        "forecast_rows": _scalar(
            connection, f"SELECT COUNT(*) FROM gold_demand_forecast{where}", params
        ),
        "series": _scalar(
            connection,
            f"""
            SELECT COUNT(DISTINCT product_id || '|' || site_id)
            FROM gold_demand_forecast{where}
            """,
            params,
        ),
        "median_mape_pct": _scalar(
            connection,
            f"SELECT MEDIAN(mape_pct) FROM gold_forecast_accuracy_ml{accuracy_where}",
            accuracy_params,
        ),
        "beats_naive_pct": _scalar(
            connection,
            f"""
            SELECT 100.0 * AVG(CASE WHEN beats_naive_mae THEN 1 ELSE 0 END)
            FROM gold_forecast_accuracy_ml{accuracy_where}
            """,
            accuracy_params,
        ),
    }
    series = _rows(
        connection,
        f"""
        WITH actual_grain AS (
            SELECT product_number, site_code, month_key,
                   MAX(demand_qty) AS demand_qty
            FROM gold_ml_feature_store{feature_where}
            {"AND" if feature_where else "WHERE"} is_actual = 1
            GROUP BY product_number, site_code, month_key
        ),
        actual AS (
            SELECT month_key AS period, SUM(demand_qty) AS value
            FROM actual_grain GROUP BY month_key
        ),
        forecast AS (
            SELECT forecast_month_key AS period,
                   SUM(demand_forecast) AS secondary
            FROM gold_demand_forecast{where}
            GROUP BY forecast_month_key
        )
        SELECT COALESCE(actual.period, forecast.period) AS period,
               actual.value, forecast.secondary
        FROM actual FULL OUTER JOIN forecast USING (period)
        ORDER BY period
        """,
        [*feature_params, *params],
    )
    rankings = _rows(
        connection,
        f"""
        SELECT pm.product_description || ' · ' || rs.site_name AS label,
               mape_pct AS value,
               mae AS secondary
        FROM gold_forecast_accuracy_ml accuracy
        LEFT JOIN slvr_prod_master pm ON accuracy.product_id = pm.product_number
        LEFT JOIN slvr_ref_site rs ON accuracy.site_id = rs.site_code
        {accuracy_where}
        ORDER BY mape_pct DESC NULLS LAST LIMIT ?
        """,
        [*accuracy_params, min(limit, 20)],
    )
    rows = _rows(
        connection,
        f"""
        SELECT forecast.product_id AS product_number,
               pm.product_description,
               forecast.site_id AS site_code,
               rs.site_name,
               forecast_month_key,
               demand_forecast,
               forecast_method
        FROM gold_demand_forecast forecast
        LEFT JOIN slvr_prod_master pm ON forecast.product_id = pm.product_number
        LEFT JOIN slvr_ref_site rs ON forecast.site_id = rs.site_code
        {where}
        ORDER BY forecast_month_key, site_id, product_id LIMIT ?
        """,
        [*params, limit],
    )
    return {
        "workflow": "demand",
        "scope": "MONTHLY_FORECAST",
        "kpis": kpis,
        "series": series,
        "rankings": rankings,
        "rows": rows,
        "charts": [
            {
                "kind": "comparison_line",
                "title": "Actual demand vs forecast",
                "unit": "units",
                "primary_label": "Actual demand",
                "secondary_label": "Forecast demand",
                "points": series,
            },
            {
                "kind": "ranking",
                "title": "Highest forecast error",
                "unit": "percent",
                "points": rankings,
            },
        ],
    }


def _yield_dashboard(connection, filters, limit) -> dict[str, Any]:
    where, params = _where(connection, "gold_yield_predictions", filters)
    kpis = {
        "prediction_rows": _scalar(
            connection, f"SELECT COUNT(*) FROM gold_yield_predictions{where}", params
        ),
        "mean_abs_error_pp": _scalar(
            connection,
            f"SELECT AVG(abs_error_pp) FROM gold_yield_predictions{where}",
            params,
        ),
        "measured_yield_pct": _scalar(
            connection,
            f"SELECT 100 * AVG(measured_yield) FROM gold_yield_predictions{where}",
            params,
        ),
        "predicted_yield_pct": _scalar(
            connection,
            f"SELECT 100 * AVG(predicted_yield) FROM gold_yield_predictions{where}",
            params,
        ),
    }
    series = _rows(
        connection,
        f"""
        SELECT month AS period, 100 * AVG(measured_yield) AS value,
               100 * AVG(predicted_yield) AS secondary,
               100 * AVG(target_yield) AS target
        FROM gold_yield_predictions{where}
        GROUP BY month ORDER BY month
        """,
        params,
    )
    rankings = _rows(
        connection,
        f"""
        SELECT pm.product_description || ' · ' || rs.site_name || ' · ' ||
               tt.test_category_name AS label,
               AVG(abs_error_pp) AS value, COUNT(*) AS secondary
        FROM gold_yield_predictions prediction
        LEFT JOIN slvr_prod_master pm ON prediction.product_id = pm.product_number
        LEFT JOIN slvr_ref_site rs ON prediction.site_id = rs.site_code
        LEFT JOIN slvr_ref_test_type tt ON prediction.test_type_id = tt.test_type
        {where}
        GROUP BY product_id, pm.product_description,
                 site_id, rs.site_name,
                 test_type_id, tt.test_category_name
        ORDER BY value DESC LIMIT ?
        """,
        [*params, min(limit, 20)],
    )
    rows = _rows(
        connection,
        f"""
        SELECT prediction.site_id AS site_code, rs.site_name,
               prediction.product_id AS product_number, pm.product_description,
               prediction.test_type_id AS test_type, tt.test_category_name AS test_type_name,
               month, measured_yield,
               predicted_yield, target_yield, abs_error_pp, split_role
        FROM gold_yield_predictions prediction
        LEFT JOIN slvr_prod_master pm ON prediction.product_id = pm.product_number
        LEFT JOIN slvr_ref_site rs ON prediction.site_id = rs.site_code
        LEFT JOIN slvr_ref_test_type tt ON prediction.test_type_id = tt.test_type
        {where}
        ORDER BY abs_error_pp DESC LIMIT ?
        """,
        [*params, limit],
    )
    drivers = _rows(
        connection,
        f"""
        SELECT shap.feature AS label, AVG(shap.abs_shap) AS value,
               AVG(shap.shap_value) AS secondary
        FROM gold_yield_shap AS shap
        JOIN (
            SELECT feature_row_id FROM gold_yield_predictions{where}
        ) AS prediction USING (feature_row_id)
        GROUP BY shap.feature
        ORDER BY value DESC LIMIT 12
        """,
        params,
    )
    return {
        "workflow": "yield",
        "scope": "MONTHLY_ML_PREDICTION",
        "kpis": kpis,
        "series": series,
        "rankings": rankings,
        "drivers": drivers,
        "rows": rows,
        "operational": _operational_panel(connection, filters),
        "charts": [
            {
                "kind": "target_line",
                "title": "Measured, predicted, and target yield",
                "unit": "percent",
                "primary_label": "Measured",
                "secondary_label": "Predicted",
                "target_label": "Target",
                "points": series,
            },
            {
                "kind": "ranking",
                "title": "Yield prediction drivers",
                "unit": "shap",
                "points": drivers,
            },
        ],
    }


def _risk_dashboard(connection, filters, limit) -> dict[str, Any]:
    where, params = _where(connection, "gold_maintenance_risk", filters)
    kpis = {
        "scores": _scalar(
            connection, f"SELECT COUNT(*) FROM gold_maintenance_risk{where}", params
        ),
        "mean_risk_pct": _scalar(
            connection,
            f"SELECT 100 * AVG(degradation_prob) FROM gold_maintenance_risk{where}",
            params,
        ),
        "high_critical": _scalar(
            connection,
            f"""
            SELECT COUNT(*) FROM gold_maintenance_risk{where}
            {"AND" if where else "WHERE"} risk_tier IN ('HIGH', 'CRITICAL')
            """,
            params,
        ),
        "equipment": _scalar(
            connection,
            f"SELECT COUNT(DISTINCT equipment_id) FROM gold_maintenance_risk{where}",
            params,
        ),
    }
    series = _rows(
        connection,
        f"""
        SELECT month AS period, 100 * AVG(degradation_prob) AS value,
               SUM(CASE WHEN risk_tier IN ('HIGH', 'CRITICAL') THEN 1 ELSE 0 END) AS secondary
        FROM gold_maintenance_risk{where}
        GROUP BY month ORDER BY month
        """,
        params,
    )
    rankings = _rows(
        connection,
        f"""
        SELECT equipment.equipment_name || ' · ' || site.site_name || ' · ' ||
               test.test_category_name AS label,
               100 * MAX(degradation_prob) AS value, MIN(avg_oee) AS secondary
        FROM gold_maintenance_risk risk
        LEFT JOIN (
            SELECT equipment_id AS ref_equipment_id, equipment_name
            FROM slvr_ref_equipment
        ) equipment ON risk.equipment_id = equipment.ref_equipment_id
        LEFT JOIN slvr_ref_site site ON risk.site_id = site.site_code
        LEFT JOIN slvr_ref_test_type test ON risk.test_type_id = test.test_type
        {where}
        GROUP BY risk.equipment_id, equipment.equipment_name,
                 risk.site_id, site.site_name,
                 risk.test_type_id, test.test_category_name
        ORDER BY value DESC LIMIT ?
        """,
        [*params, min(limit, 20)],
    )
    rows = _rows(
        connection,
        f"""
        SELECT risk.equipment_id, equipment.equipment_name,
               risk.site_id AS site_code, site.site_name,
               risk.test_type_id AS test_type, test.test_category_name AS test_type_name,
               month, avg_oee,
               degradation_prob, risk_tier, split_role
        FROM gold_maintenance_risk risk
        LEFT JOIN (
            SELECT equipment_id AS ref_equipment_id, equipment_name
            FROM slvr_ref_equipment
        ) equipment ON risk.equipment_id = equipment.ref_equipment_id
        LEFT JOIN slvr_ref_site site ON risk.site_id = site.site_code
        LEFT JOIN slvr_ref_test_type test ON risk.test_type_id = test.test_type
        {where}
        ORDER BY degradation_prob DESC LIMIT ?
        """,
        [*params, limit],
    )
    distribution = _rows(
        connection,
        f"""
        SELECT risk_tier AS label, COUNT(*) AS value
        FROM gold_maintenance_risk{where}
        GROUP BY risk_tier
        ORDER BY value DESC
        """,
        params,
    )
    return {
        "workflow": "oee-risk",
        "scope": "MONTHLY_DEGRADATION_RISK",
        "kpis": kpis,
        "series": series,
        "rankings": rankings,
        "distribution": distribution,
        "rows": rows,
        "operational": _operational_panel(connection, filters),
        "charts": [
            {
                "kind": "single_line",
                "title": "Degradation risk over time",
                "unit": "percent",
                "primary_label": "Mean degradation risk",
                "points": series,
            },
            {
                "kind": "categorical",
                "title": "Risk tier distribution",
                "unit": "records",
                "points": distribution,
            },
        ],
    }


def _anomaly_dashboard(connection, filters, limit) -> dict[str, Any]:
    where, params = _where(connection, "gold_oee_anomalies", filters)
    kpis = {
        "scored_rows": _scalar(
            connection, f"SELECT COUNT(*) FROM gold_oee_anomalies{where}", params
        ),
        "anomaly_count": _scalar(
            connection,
            f"SELECT SUM(anomaly_flag) FROM gold_oee_anomalies{where}",
            params,
        ),
        "anomaly_rate_pct": _scalar(
            connection,
            f"SELECT 100 * AVG(anomaly_flag) FROM gold_oee_anomalies{where}",
            params,
        ),
        "sites": _scalar(
            connection,
            f"SELECT COUNT(DISTINCT site_id) FROM gold_oee_anomalies{where}",
            params,
        ),
    }
    series = _rows(
        connection,
        f"""
        SELECT month AS period, 100 * AVG(avg_oee) AS value,
               SUM(anomaly_flag) AS secondary
        FROM gold_oee_anomalies{where}
        GROUP BY month ORDER BY month
        """,
        params,
    )
    rankings = _rows(
        connection,
        f"""
        SELECT site.site_name || ' · ' || test.test_category_name AS label,
               SUM(anomaly_flag) AS value, 100 * AVG(avg_oee) AS secondary
        FROM gold_oee_anomalies anomaly
        LEFT JOIN slvr_ref_site site ON anomaly.site_id = site.site_code
        LEFT JOIN slvr_ref_test_type test ON anomaly.test_type_id = test.test_type
        {where}
        GROUP BY anomaly.site_id, site.site_name,
                 anomaly.test_type_id, test.test_category_name
        ORDER BY value DESC LIMIT ?
        """,
        [*params, min(limit, 20)],
    )
    rows = _rows(
        connection,
        f"""
        SELECT anomaly.equipment_id, equipment.equipment_name,
               anomaly.site_id AS site_code, site.site_name,
               anomaly.test_type_id AS test_type, test.test_category_name AS test_type_name,
               month, avg_oee,
               anomaly_score, anomaly_severity, anomaly_driver
        FROM gold_oee_anomalies anomaly
        LEFT JOIN (
            SELECT equipment_id AS ref_equipment_id, equipment_name
            FROM slvr_ref_equipment
        ) equipment ON anomaly.equipment_id = equipment.ref_equipment_id
        LEFT JOIN slvr_ref_site site ON anomaly.site_id = site.site_code
        LEFT JOIN slvr_ref_test_type test ON anomaly.test_type_id = test.test_type
        {where}
        ORDER BY anomaly_score LIMIT ?
        """,
        [*params, limit],
    )
    distribution = _rows(
        connection,
        f"""
        SELECT anomaly_severity AS label, COUNT(*) AS value
        FROM gold_oee_anomalies{where}
        GROUP BY anomaly_severity
        ORDER BY value DESC
        """,
        params,
    )
    return {
        "workflow": "oee-anomaly",
        "scope": "MONTHLY_HOLDOUT_EVALUATION",
        "kpis": kpis,
        "series": series,
        "rankings": rankings,
        "distribution": distribution,
        "rows": rows,
        "operational": _operational_panel(connection, filters),
        "charts": [
            {
                "kind": "single_line",
                "title": "OEE across the evaluation window",
                "unit": "percent",
                "primary_label": "Mean OEE",
                "points": series,
            },
            {
                "kind": "categorical",
                "title": "Anomaly severity",
                "unit": "records",
                "points": distribution,
            },
        ],
        "notice": "Anomaly scores describe the holdout evaluation window, not live monitoring.",
    }


def _capex_dashboard(connection, filters, limit) -> dict[str, Any]:
    where, params = _where(connection, "gold_capex_mc_summary", filters)
    scenario_where, scenario_params = _where(
        connection, "gold_capex_mc_scenarios", filters
    )
    kpis = {
        "combinations": _scalar(
            connection, f"SELECT COUNT(*) FROM gold_capex_mc_summary{where}", params
        ),
        "capex_p80_usd": _scalar(
            connection,
            f"SELECT SUM(capex_usd_p80) FROM gold_capex_mc_summary{where}",
            params,
        ),
        "equipment_p80": _scalar(
            connection,
            f"SELECT SUM(eq_needed_p80) FROM gold_capex_mc_summary{where}",
            params,
        ),
        "investment_combinations": _scalar(
            connection,
            f"""
            SELECT SUM(CASE WHEN delta_units_p80 > 0 THEN 1 ELSE 0 END)
            FROM gold_capex_mc_summary{where}
            """,
            params,
        ),
    }
    rankings = _rows(
        connection,
        f"""
        SELECT site.site_name || ' · ' || test.test_category_name AS label,
               capex_usd_p80 AS value, delta_units_p80 AS secondary
        FROM gold_capex_mc_summary capex
        LEFT JOIN (
            SELECT site_code AS ref_site_code, site_name FROM slvr_ref_site
        ) site ON capex.site_code = site.ref_site_code
        LEFT JOIN (
            SELECT test_type AS ref_test_type, test_category_name
            FROM slvr_ref_test_type
        ) test ON capex.test_type = test.ref_test_type
        {where}
        ORDER BY value DESC LIMIT ?
        """,
        [*params, min(limit, 20)],
    )
    rows = _rows(
        connection,
        f"""
        SELECT capex.site_code, site.site_name,
               capex.test_type, test.test_category_name AS test_type_name,
               current_equipment_qty, eq_needed_p50,
               eq_needed_p80, eq_needed_p95, delta_units_p80, capex_usd_p80
        FROM gold_capex_mc_summary capex
        LEFT JOIN (
            SELECT site_code AS ref_site_code, site_name FROM slvr_ref_site
        ) site ON capex.site_code = site.ref_site_code
        LEFT JOIN (
            SELECT test_type AS ref_test_type, test_category_name
            FROM slvr_ref_test_type
        ) test ON capex.test_type = test.ref_test_type
        {where}
        ORDER BY capex_usd_p80 DESC LIMIT ?
        """,
        [*params, limit],
    )
    scenarios = _rows(
        connection,
        f"""
        SELECT site_code, test_type, scenario, equipment_qty,
               probability_sufficient, capex_usd
        FROM gold_capex_mc_scenarios
        {scenario_where}
        ORDER BY capex_usd DESC
        LIMIT ?
        """,
        [*scenario_params, limit],
    )
    return {
        "workflow": "capex",
        "scope": "MONTE_CARLO_SCENARIO",
        "kpis": kpis,
        "series": [],
        "rankings": rankings,
        "scenarios": scenarios,
        "rows": rows,
        "charts": [
            {
                "kind": "percentile_range",
                "title": "P50, P80, and P95 equipment requirement",
                "unit": "equipment",
                "points": rows[:12],
            },
            {
                "kind": "categorical",
                "title": "P80 capital exposure",
                "unit": "usd",
                "points": rankings,
            },
        ],
    }
