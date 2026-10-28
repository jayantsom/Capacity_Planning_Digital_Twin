"""Release-pinned read access shared by dashboards and Yukti."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from capacity_twin_core.runtime.database_paths import (
    get_release_pointer,
    get_runtime_home,
)

SERVING_ALIASES = {
    "gold_ml_feature_store": "srv_ml_feature_store",
    "gold_oee_metrics": "srv_oee_metrics",
    "gold_cap_actual": "srv_actual_output",
    "gold_gcm_base": "srv_gcm_resource_contract",
    "gold_operational_performance": "srv_vw_operational_performance",
    "gold_operational_events": "srv_vw_operational_events",
}

REFERENCE_ALIASES = {
    "slvr_ref_site": "site",
    "slvr_prod_master": "product",
    "slvr_ref_test_type": "test_type",
    "slvr_ref_equipment": "machine",
}

ML_ALIASES = {
    "gold_demand_forecast": "ml_demand_forecast",
    "gold_forecast_accuracy_ml": "ml_forecast_accuracy",
    "gold_yield_predictions": "ml_yield_predictions",
    "gold_yield_shap": "ml_yield_shap",
    "gold_cap_ml_adjusted": "ml_capacity_adjusted",
    "gold_maintenance_risk": "ml_oee_degradation_risk",
    "gold_maintenance_alerts": "ml_oee_degradation_alerts",
    "gold_oee_anomalies": "ml_oee_anomalies",
    "gold_oee_anomaly_summary": "ml_oee_anomaly_summary",
    "gold_capex_mc_summary": "ml_capex_summary",
    "gold_capex_mc_scenarios": "ml_capex_scenarios",
}


def _release_path(runtime: Path, value: str) -> Path:
    path = Path(value)
    resolved = (path if path.is_absolute() else runtime / path).resolve()
    if runtime not in resolved.parents:
        raise ValueError("Release path escapes the runtime home")
    return resolved


def _attach(connection: duckdb.DuckDBPyConnection, alias: str, path: Path) -> None:
    escaped = str(path).replace("'", "''")
    connection.execute(f"ATTACH '{escaped}' AS {alias} (READ_ONLY)")


def open_analytics_connection() -> duckdb.DuckDBPyConnection:
    """Open one compatible Serving, Reference, and ML release."""
    runtime = get_runtime_home().resolve()
    release_path = get_release_pointer(runtime)
    if not release_path.is_file():
        raise FileNotFoundError("No compatible release publication")
    release = json.loads(release_path.read_text(encoding="utf-8"))
    serving = _release_path(runtime, release["publications"]["serving"]["path"])
    ml_path = _release_path(runtime, release["ml"]["path"])
    source_manifest = _release_path(runtime, release["source_bundle"]["manifest"])
    source = json.loads(source_manifest.read_text(encoding="utf-8"))
    reference_detail = next(
        value for value in source["files"].values() if value["role"] == "reference"
    )
    reference = _release_path(runtime, reference_detail["path"])

    connection = duckdb.connect(":memory:")
    try:
        for alias, path in (
            ("serving", serving),
            ("reference", reference),
            ("ml", ml_path),
        ):
            _attach(connection, alias, path)
        for legacy, table in SERVING_ALIASES.items():
            connection.execute(
                f'CREATE OR REPLACE TEMP VIEW "{legacy}" AS '
                f'SELECT * FROM serving."{table}"'
            )
        for legacy, table in REFERENCE_ALIASES.items():
            connection.execute(
                f'CREATE OR REPLACE TEMP VIEW "{legacy}" AS '
                f'SELECT * FROM reference.canonical."{table}"'
            )
        ml_tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_catalog = 'ml' AND table_schema = 'main'
                """
            ).fetchall()
        }
        for table in ml_tables:
            connection.execute(
                f'CREATE OR REPLACE TEMP VIEW "{table}" AS SELECT * FROM ml."{table}"'
            )
        for legacy, table in ML_ALIASES.items():
            if table in ml_tables:
                connection.execute(
                    f'CREATE OR REPLACE TEMP VIEW "{legacy}" AS '
                    f'SELECT * FROM ml."{table}"'
                )
        return connection
    except Exception:
        connection.close()
        raise
