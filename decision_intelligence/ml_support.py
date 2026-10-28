"""Point-in-time features, safe metrics, and trusted model artifacts."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import pickle
import platform
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from capacity_twin_core.runtime.analytics import open_analytics_connection
from capacity_twin_core.runtime.database_paths import (
    get_active_run_pointer,
    get_release_pointer,
    get_runtime_home,
    load_app_config,
)

PIPELINE_CONFIG = load_app_config("data_operations.pipeline")
ML_CONFIG = load_app_config("decision_intelligence")
_ACTIVE_DB_PATH: Path | None = None
_ACTIVE_MODELS_DIR: Path | None = None
_ACTIVE_INPUT_PATHS: dict[str, Path] | None = None

ML_OUTPUT_NAME_MAP = {
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

SERVING_INPUT_ALIASES = {
    "gold_ml_feature_store": "srv_ml_feature_store",
    "gold_oee_metrics": "srv_oee_metrics",
    "gold_cap_actual": "srv_actual_output",
    "gold_gcm_base": "srv_gcm_resource_contract",
    "gold_operational_performance": "srv_vw_operational_performance",
    "gold_operational_events": "srv_vw_operational_events",
}

REFERENCE_INPUT_ALIASES = {
    "slvr_ref_site": "site",
    "slvr_prod_master": "product",
    "slvr_ref_test_type": "test_type",
    "slvr_ref_equipment": "machine",
}


def source_database_path() -> Path:
    """Return the self-contained Serving input with Gold facts and dimensions."""
    runtime = get_runtime_home()
    release_pointer = get_release_pointer(runtime)
    if release_pointer.is_file():
        release = json.loads(release_pointer.read_text(encoding="utf-8"))
        details = release.get("publications", {}).get("serving", {})
        if details.get("path"):
            candidate = Path(details["path"])
            return candidate if candidate.is_absolute() else runtime / candidate
    pointer = get_active_run_pointer(runtime)
    if pointer.is_file():
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        run_id = payload.get("active_run_id")
        if not run_id:
            raise ValueError("Pipeline pointer has no active_run_id")
        database_name = PIPELINE_CONFIG["databases"].get(
            "serving", "serving.duckdb"
        )
        candidate = (runtime / "artifacts" / run_id / database_name).resolve()
        if runtime.resolve() not in candidate.parents:
            raise ValueError("Pipeline pointer escapes the runtime home")
        return candidate
    database_name = PIPELINE_CONFIG["databases"].get(
        "serving", "serving.duckdb"
    )
    return runtime / database_name


def published_database_path() -> Path:
    """Return the external ML publication database."""
    runtime = get_runtime_home()
    release_pointer = get_release_pointer(runtime)
    if release_pointer.is_file():
        release = json.loads(release_pointer.read_text(encoding="utf-8"))
        details = release.get("ml") or {}
        if details.get("path"):
            candidate = Path(details["path"])
            candidate = candidate if candidate.is_absolute() else runtime / candidate
            resolved = candidate.resolve()
            if runtime.resolve() not in resolved.parents:
                raise ValueError("Release ML path escapes the runtime home")
            return resolved
    pointer = runtime / "ml_current.json"
    if pointer.is_file():
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        candidate = (runtime / payload["database"]).resolve()
        if runtime.resolve() not in candidate.parents:
            raise ValueError("ML publication pointer escapes the runtime home")
        return candidate
    return runtime / ML_CONFIG["publication"]["database"]


def set_active_paths(
    database_path: Path | None = None,
    models_dir: Path | None = None,
    *,
    input_paths: dict[str, Path] | None = None,
) -> None:
    """Point one staged run at its candidate database and model directory."""
    global _ACTIVE_DB_PATH, _ACTIVE_MODELS_DIR, _ACTIVE_INPUT_PATHS
    _ACTIVE_DB_PATH = database_path
    _ACTIVE_MODELS_DIR = models_dir
    _ACTIVE_INPUT_PATHS = input_paths


def _attach_catalogs(
    connection: duckdb.DuckDBPyConnection,
    inputs: dict[str, Path],
) -> None:
    for alias, path in inputs.items():
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(f"ATTACH '{escaped}' AS {alias} (READ_ONLY)")
    for legacy, serving_table in SERVING_INPUT_ALIASES.items():
        connection.execute(
            f'CREATE OR REPLACE TEMP VIEW "{legacy}" AS '
            f'SELECT * FROM serving."{serving_table}"'
        )
    for legacy, reference_table in REFERENCE_INPUT_ALIASES.items():
        connection.execute(
            f'CREATE OR REPLACE TEMP VIEW "{legacy}" AS '
            f'SELECT * FROM reference.canonical."{reference_table}"'
        )
    local_tables = {
        row[0]
        for row in connection.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_catalog = current_database() AND table_type = 'BASE TABLE'
            """
        ).fetchall()
    }
    for legacy, published in ML_OUTPUT_NAME_MAP.items():
        if published in local_tables:
            connection.execute(
                f'CREATE OR REPLACE TEMP VIEW "{legacy}" AS '
                f'SELECT * FROM "{published}"'
            )


def get_conn(*, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open the active candidate, or the source database for compatibility."""
    path = _ACTIVE_DB_PATH or source_database_path()
    if not path.is_file() and read_only:
        raise FileNotFoundError(f"ML input database not found: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path), read_only=read_only)
    if _ACTIVE_INPUT_PATHS:
        _attach_catalogs(connection, _ACTIVE_INPUT_PATHS)
    return connection


def _table_exists(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?",
            [table],
        ).fetchone()[0]
    )


def load_feature_store(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Load point-in-time ML rows with measured yield and complete merge keys."""
    if not _table_exists(conn, "gold_ml_feature_store"):
        raise ValueError("Missing required table: gold_ml_feature_store")
    fs = conn.execute("SELECT * FROM gold_ml_feature_store").df()
    required = {
        "site_code",
        "product_number",
        "test_type",
        "month_key",
        "planning_version_id",
        "demand_qty",
        "target_yield",
    }
    missing = sorted(required - set(fs.columns))
    if missing:
        raise ValueError(f"Feature store missing columns: {missing}")

    key_cols = ["site_code", "product_number", "test_type", "month_key", "planning_version_id"]
    if fs[key_cols].isna().any().any():
        raise ValueError("Feature store contains null business keys")

    # Gold may contain one row per qualified resource. ML labels are defined at
    # product/site/test/month/planning version grain, so remove resource fan-out first.
    contract_cols = ["demand_qty", "target_yield", "target_test_time_sec", "is_actual"]
    for column in contract_cols:
        if column not in fs:
            continue
        conflicts = fs.groupby(key_cols, dropna=False)[column].nunique(dropna=True)
        if (conflicts > 1).any():
            raise ValueError(f"Feature store has conflicting {column} values at ML grain")

    unsafe_columns = {
        "feat_pk",
        "equip_qty_available",
        "utilization_rate",
    }
    unsafe_columns.update(
        column
        for column in fs.columns
        if "_lag_" in column or "_roll_" in column
    )
    collapsed = fs.drop(columns=sorted(unsafe_columns & set(fs.columns)))
    value_cols = [column for column in collapsed.columns if column not in key_cols]
    fs = (
        collapsed.sort_values(key_cols)
        .groupby(key_cols, as_index=False, dropna=False)[value_cols]
        .first()
    )

    # OEE is measured at site/test/month. Aggregate first so the merge is many-to-one.
    if _table_exists(conn, "gold_oee_metrics"):
        oee = conn.execute(
            """
            SELECT site_code, test_type, month_key,
                   AVG(oee_pct) AS measured_oee,
                   AVG(availability_pct) AS availability,
                   AVG(performance_pct) AS performance,
                   AVG(quality_pct) AS quality
            FROM gold_oee_metrics
            GROUP BY site_code, test_type, month_key
            """
        ).df()
        fs = fs.merge(
            oee,
            on=["site_code", "test_type", "month_key"],
            how="left",
            validate="many_to_one",
        )

    # The label is measured execution yield. Target yield remains a covariate.
    if _table_exists(conn, "gold_cap_actual"):
        actual = conn.execute(
            """
            SELECT site_code, product_number, test_type, month_key,
                   AVG(actual_yield_avg) AS measured_yield
            FROM gold_cap_actual
            GROUP BY site_code, product_number, test_type, month_key
            """
        ).df()
        fs = fs.merge(
            actual,
            on=["site_code", "product_number", "test_type", "month_key"],
            how="left",
            validate="many_to_one",
        )
    else:
        fs["measured_yield"] = np.nan

    renamed = fs.rename(
        columns={
            "product_number": "product_id",
            "site_code": "site_id",
            "platform": "platform_id",
            "product_family": "family_id",
            "test_type": "test_type_id",
            "month_key": "month",
            "demand_qty": "demand",
            "measured_oee": "avg_oee",
            "target_yield": "target_yield",
        }
    )
    renamed_keys = ["site_id", "product_id", "test_type_id", "month", "planning_version_id"]
    renamed["feature_row_id"] = stable_row_ids(renamed, renamed_keys)
    return renamed


def load_table(conn: duckdb.DuckDBPyConnection, table: str) -> pd.DataFrame:
    """Load a trusted internal table name."""
    if not table.replace("_", "").isalnum():
        raise ValueError(f"Invalid table name: {table}")
    physical = ML_OUTPUT_NAME_MAP.get(table, table)
    return conn.execute(f'SELECT * FROM "{physical}"').df()


def upsert_table(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame, table: str) -> int:
    """Replace one candidate output table after validating its identifier."""
    if not table.replace("_", "").isalnum():
        raise ValueError(f"Invalid table name: {table}")
    physical = ML_OUTPUT_NAME_MAP.get(table, table)
    conn.execute(f'DROP VIEW IF EXISTS "{table}"')
    conn.execute(f'DROP TABLE IF EXISTS "{physical}"')
    conn.register("_tmp", df)
    conn.execute(f'CREATE TABLE "{physical}" AS SELECT * FROM _tmp')
    conn.unregister("_tmp")
    if physical != table:
        conn.execute(
            f'CREATE OR REPLACE TEMP VIEW "{table}" AS SELECT * FROM "{physical}"'
        )
    return len(df)


def open_release_connection() -> duckdb.DuckDBPyConnection:
    """Open one release-pinned read connection over Serving, Reference, and ML."""
    return open_analytics_connection()


def _models_dir() -> Path:
    runtime = get_runtime_home()
    pointer = runtime / "ml_current.json"
    promoted_models = None
    if pointer.is_file():
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        promoted_models = (runtime / payload["models"]).resolve()
        if runtime.resolve() not in promoted_models.parents:
            raise ValueError("ML model pointer escapes the runtime home")
    path = (
        _ACTIVE_MODELS_DIR
        or promoted_models
        or (runtime / ML_CONFIG.get("model_artifact_subdir", "models"))
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_sha256(path: Path) -> str:
    """Calculate a file checksum without loading the whole file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _library_versions() -> dict[str, str]:
    versions = {}
    for package in ("numpy", "pandas", "scikit-learn", "xgboost", "lightgbm"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    return versions


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def save_model(model: Any, name: str, metadata: dict | None = None) -> Path:
    """Atomically save a model and mandatory compatibility metadata."""
    directory = _models_dir()
    pkl_path = directory / f"{name}.pkl"
    temp_path = directory / f".{name}.{os.getpid()}.tmp"
    with temp_path.open("wb") as stream:
        pickle.dump(model, stream, protocol=pickle.HIGHEST_PROTOCOL)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, pkl_path)

    supplied = dict(metadata or {})
    feature_schema = supplied.pop("feature_schema", supplied.pop("features", None))
    if not feature_schema:
        raise ValueError("Model metadata requires a non-empty feature schema")
    manifest = {
        **supplied,
        "artifact_name": name,
        "artifact_sha256": file_sha256(pkl_path),
        "feature_schema": list(feature_schema),
        "python_version": platform.python_version(),
        "library_versions": _library_versions(),
        "training_run": supplied.get(
            "training_run", os.environ.get("CAPACITY_TWIN_RUN_ID", "local")
        ),
    }
    _atomic_json(directory / f"{name}_meta.json", manifest)
    return pkl_path


def load_model(name: str) -> Any:
    """Load only a checksum-verified, Python-compatible promoted model."""
    directory = _models_dir()
    pkl_path = directory / f"{name}.pkl"
    meta_path = directory / f"{name}_meta.json"
    if not pkl_path.is_file() or not meta_path.is_file():
        raise FileNotFoundError(f"Trusted model artifact is incomplete: {name}")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    required = {"artifact_sha256", "feature_schema", "python_version", "library_versions"}
    missing = required - metadata.keys()
    if missing:
        raise ValueError(f"Model metadata missing fields: {sorted(missing)}")
    if file_sha256(pkl_path) != metadata["artifact_sha256"]:
        raise ValueError(f"Model checksum mismatch: {name}")
    trained_python = ".".join(metadata["python_version"].split(".")[:2])
    current_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    if trained_python != current_python:
        raise ValueError(
            f"Model Python version {trained_python} is incompatible with {current_python}"
        )
    current_libraries = _library_versions()
    incompatible = {
        package: {"trained": version, "current": current_libraries.get(package)}
        for package, version in metadata["library_versions"].items()
        if current_libraries.get(package) != version
    }
    if incompatible:
        raise ValueError(f"Model library versions are incompatible: {incompatible}")
    with pkl_path.open("rb") as stream:
        return pickle.load(stream)


# ── Feature helpers ─────────────────────────────────────────────────────────


def stable_row_ids(df: pd.DataFrame, key_cols: Sequence[str]) -> pd.Series:
    """Hash complete business keys into stable explanation/publication IDs."""
    missing = [col for col in key_cols if col not in df.columns]
    if missing:
        raise ValueError(f"Cannot build row IDs; missing keys: {missing}")
    keys = df[list(key_cols)].astype("string").fillna("<NULL>").agg("|".join, axis=1)
    return keys.map(lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()[:24])


def add_lag_features(
    df: pd.DataFrame,
    col: str,
    lags: list[int],
    group_cols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Add lags within a series so adjacent series can never leak."""
    grouped = df.groupby(list(group_cols), sort=False)[col] if group_cols else df[col]
    for lag in lags:
        df[f"{col}_lag{lag}"] = grouped.shift(lag)
    return df


def add_rolling_features(
    df: pd.DataFrame,
    col: str,
    windows: list[int],
    group_cols: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Add trailing statistics shifted one period behind the target row."""
    for w in windows:
        if group_cols:
            grouped = df.groupby(list(group_cols), sort=False)[col]
            df[f"{col}_roll{w}_mean"] = grouped.transform(
                lambda values, window=w: values.shift(1).rolling(window, min_periods=1).mean()
            )
            df[f"{col}_roll{w}_std"] = grouped.transform(
                lambda values, window=w: values.shift(1).rolling(window, min_periods=1).std()
            ).fillna(0)
        else:
            prior = df[col].shift(1)
            df[f"{col}_roll{w}_mean"] = prior.rolling(w, min_periods=1).mean()
            df[f"{col}_roll{w}_std"] = prior.rolling(w, min_periods=1).std().fillna(0)
    return df


def encode_categoricals(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Encode categories deterministically; callers must fit on training data only."""
    for col in cols:
        if col in df.columns:
            values = sorted(df[col].dropna().astype(str).unique())
            mapping = {value: index for index, value in enumerate(values)}
            df[col] = df[col].astype(str).map(mapping).fillna(-1).astype(int)
    return df


# ── Metrics ─────────────────────────────────────────────────────────────────


def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true != 0
    if not np.any(mask):
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def smape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2
    mask = denom != 0
    if not np.any(mask):
        return float("nan")
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom[mask]) * 100)


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) == 0:
        return float("nan")
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def temporal_split(
    df: pd.DataFrame,
    month_col: str = "month",
    holdout_months: int = 6,
    validation_months: int = 3,
    minimum_train_months: int = 6,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split by unique months, never by interleaved row positions."""
    months = sorted(pd.Series(df[month_col].dropna().unique()).astype(int).tolist())
    required = minimum_train_months + validation_months + holdout_months
    if len(months) < required:
        raise ValueError(
            f"Insufficient history: {len(months)} unique months; need at least {required}"
        )
    holdout_set = set(months[-holdout_months:])
    validation_set = set(months[-(holdout_months + validation_months) : -holdout_months])
    train = df[~df[month_col].isin(holdout_set | validation_set)].copy()
    validation = df[df[month_col].isin(validation_set)].copy()
    holdout = df[df[month_col].isin(holdout_set)].copy()
    if train[month_col].max() >= validation[month_col].min():
        raise AssertionError("Training months overlap validation months")
    if validation[month_col].max() >= holdout[month_col].min():
        raise AssertionError("Validation months overlap holdout months")
    return train, validation, holdout


def metric_result(
    y_true: Sequence[float],
    y_pred: Sequence[float],
    *,
    naive_pred: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Return explicit evaluability and regression metrics."""
    actual = np.asarray(y_true, dtype=float)
    predicted = np.asarray(y_pred, dtype=float)
    finite = np.isfinite(actual) & np.isfinite(predicted)
    actual, predicted = actual[finite], predicted[finite]
    if len(actual) == 0:
        return {"status": "not_evaluable", "reason": "no finite holdout targets"}
    if np.all(actual == 0):
        result = {
            "status": "not_evaluable",
            "reason": "holdout targets are all zero",
            "mae": float(np.mean(np.abs(predicted))),
            "rmse": rmse(actual, predicted),
            "mape_pct": None,
        }
        if naive_pred is not None:
            naive = np.asarray(naive_pred, dtype=float)[finite]
            result["naive_mae"] = float(np.mean(np.abs(actual - naive)))
            result["beats_naive_mae"] = bool(result["mae"] < result["naive_mae"])
        return result
    result: dict[str, Any] = {
        "status": "evaluated",
        "mae": float(np.mean(np.abs(actual - predicted))),
        "rmse": rmse(actual, predicted),
        "mape_pct": mape(actual, predicted),
    }
    if naive_pred is not None:
        naive = np.asarray(naive_pred, dtype=float)[finite]
        result["naive_mae"] = float(np.mean(np.abs(actual - naive)))
        result["beats_naive_mae"] = bool(result["mae"] < result["naive_mae"])
    return result
