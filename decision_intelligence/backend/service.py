"""Read-only dashboard queries and ML job orchestration."""

from __future__ import annotations

import json
from typing import Any

import duckdb

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


def dashboard(
    workflow: str,
    *,
    site: str | None = None,
    product: str | None = None,
    test_type: str | None = None,
    snapshot: str | None = None,
    month_from: int | None = None,
    month_to: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return one allowlisted dashboard payload."""
    if workflow not in WORKFLOW_KEYS:
        raise KeyError(workflow)
    filters = {
        "site": site,
        "product": product,
        "test_type": test_type,
        "snapshot": snapshot,
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
        "snapshot": ("snapshot_id",),
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
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), parameters


def _rows(connection, sql: str, parameters: list[Any] | None = None) -> list[dict]:
    frame = connection.execute(sql, parameters or []).df()
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _scalar(connection, sql: str, parameters: list[Any] | None = None) -> Any:
    value = connection.execute(sql, parameters or []).fetchone()[0]
    return value.item() if hasattr(value, "item") else value


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
        SELECT product_id || ' · ' || site_id AS label, mape_pct AS value,
               mae AS secondary
        FROM gold_forecast_accuracy_ml{accuracy_where}
        ORDER BY mape_pct DESC NULLS LAST LIMIT ?
        """,
        [*accuracy_params, min(limit, 20)],
    )
    rows = _rows(
        connection,
        f"""
        SELECT product_id, site_id, forecast_month_key, demand_forecast,
               forecast_method
        FROM gold_demand_forecast{where}
        ORDER BY forecast_month_key, site_id, product_id LIMIT ?
        """,
        [*params, limit],
    )
    return {"kpis": kpis, "series": series, "rankings": rankings, "rows": rows}


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
               100 * AVG(predicted_yield) AS secondary
        FROM gold_yield_predictions{where}
        GROUP BY month ORDER BY month
        """,
        params,
    )
    rankings = _rows(
        connection,
        f"""
        SELECT product_id || ' · ' || site_id || ' · ' || test_type_id AS label,
               AVG(abs_error_pp) AS value, COUNT(*) AS secondary
        FROM gold_yield_predictions{where}
        GROUP BY product_id, site_id, test_type_id
        ORDER BY value DESC LIMIT ?
        """,
        [*params, min(limit, 20)],
    )
    rows = _rows(
        connection,
        f"""
        SELECT site_id, product_id, test_type_id, month, measured_yield,
               predicted_yield, target_yield, abs_error_pp, split_role
        FROM gold_yield_predictions{where}
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
        "kpis": kpis,
        "series": series,
        "rankings": rankings,
        "drivers": drivers,
        "rows": rows,
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
        SELECT equipment_id || ' · ' || site_id || ' · ' || test_type_id AS label,
               100 * MAX(degradation_prob) AS value, MIN(avg_oee) AS secondary
        FROM gold_maintenance_risk{where}
        GROUP BY equipment_id, site_id, test_type_id
        ORDER BY value DESC LIMIT ?
        """,
        [*params, min(limit, 20)],
    )
    rows = _rows(
        connection,
        f"""
        SELECT equipment_id, site_id, test_type_id, month, avg_oee,
               degradation_prob, risk_tier, split_role
        FROM gold_maintenance_risk{where}
        ORDER BY degradation_prob DESC LIMIT ?
        """,
        [*params, limit],
    )
    return {"kpis": kpis, "series": series, "rankings": rankings, "rows": rows}


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
        SELECT site_id || ' · ' || test_type_id AS label,
               SUM(anomaly_flag) AS value, 100 * AVG(avg_oee) AS secondary
        FROM gold_oee_anomalies{where}
        GROUP BY site_id, test_type_id
        ORDER BY value DESC LIMIT ?
        """,
        [*params, min(limit, 20)],
    )
    rows = _rows(
        connection,
        f"""
        SELECT equipment_id, site_id, test_type_id, month, avg_oee,
               anomaly_score, anomaly_severity, anomaly_driver
        FROM gold_oee_anomalies{where}
        ORDER BY anomaly_score LIMIT ?
        """,
        [*params, limit],
    )
    return {"kpis": kpis, "series": series, "rankings": rankings, "rows": rows}


def _capex_dashboard(connection, filters, limit) -> dict[str, Any]:
    where, params = _where(connection, "gold_capex_mc_summary", filters)
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
        SELECT site_code || ' · ' || test_type AS label,
               capex_usd_p80 AS value, delta_units_p80 AS secondary
        FROM gold_capex_mc_summary{where}
        ORDER BY value DESC LIMIT ?
        """,
        [*params, min(limit, 20)],
    )
    rows = _rows(
        connection,
        f"""
        SELECT site_code, test_type, current_equipment_qty, eq_needed_p50,
               eq_needed_p80, eq_needed_p95, delta_units_p80, capex_usd_p80
        FROM gold_capex_mc_summary{where}
        ORDER BY capex_usd_p80 DESC LIMIT ?
        """,
        [*params, limit],
    )
    return {"kpis": kpis, "series": [], "rankings": rankings, "rows": rows}
