"""
Shared utilities for all ML models.
Handles DuckDB connection, feature loading, model save/load, and metrics.
"""

import json
import pickle
import warnings
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)

# ── Paths ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "capacity_planning_twin.duckdb"
MODELS_DIR = PROJECT_ROOT / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)


# ── DuckDB ─────────────────────────────────────────────────────────────────

def get_conn() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH))


def load_feature_store(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Load gold_ml_feature_store and join oee_pct from gold_oee_metrics.
    Normalises column names to a stable internal set used by all ML models.
    """
    fs = conn.execute("SELECT * FROM gold_ml_feature_store").df()

    # Join OEE — match on site_code + test_type + month_key
    oee = conn.execute(
        "SELECT site_code, test_type, month_key, oee_pct FROM gold_oee_metrics"
    ).df()
    fs = fs.merge(oee, on=["site_code", "test_type", "month_key"], how="left")

    # ── Rename to stable internal names used throughout ML code ────────────
    fs = fs.rename(columns={
        "product_number":   "product_id",
        "site_code":        "site_id",
        "platform":         "platform_id",
        "product_family":   "family_id",
        "test_type":        "test_type_id",
        "month_key":        "month",        # INTEGER yyyymm
        "demand_qty":       "demand",
        "target_yield":     "avg_yield",
        "oee_pct":          "avg_oee",
    })

    return fs


def load_table(conn: duckdb.DuckDBPyConnection, table: str) -> pd.DataFrame:
    return conn.execute(f"SELECT * FROM {table}").df()


def upsert_table(conn: duckdb.DuckDBPyConnection, df: pd.DataFrame, table: str) -> int:
    conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.register("_tmp", df)
    conn.execute(f"CREATE TABLE {table} AS SELECT * FROM _tmp")
    conn.unregister("_tmp")
    return len(df)


# ── Model persistence ───────────────────────────────────────────────────────

def save_model(model: Any, name: str, metadata: dict | None = None) -> Path:
    pkl_path = MODELS_DIR / f"{name}.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(model, f)
    if metadata:
        meta_path = MODELS_DIR / f"{name}_meta.json"
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
    return pkl_path


def load_model(name: str) -> Any:
    pkl_path = MODELS_DIR / f"{name}.pkl"
    with open(pkl_path, "rb") as f:
        return pickle.load(f)


# ── Feature helpers ─────────────────────────────────────────────────────────

def add_lag_features(df: pd.DataFrame, col: str, lags: list[int]) -> pd.DataFrame:
    for lag in lags:
        df[f"{col}_lag{lag}"] = df[col].shift(lag)
    return df


def add_rolling_features(df: pd.DataFrame, col: str, windows: list[int]) -> pd.DataFrame:
    for w in windows:
        df[f"{col}_roll{w}_mean"] = df[col].rolling(w, min_periods=1).mean()
        df[f"{col}_roll{w}_std"]  = df[col].rolling(w, min_periods=1).std().fillna(0)
    return df


def encode_categoricals(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for col in cols:
        if col in df.columns:
            df[col] = df[col].astype("category").cat.codes
    return df


# ── Metrics ─────────────────────────────────────────────────────────────────

def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true != 0
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def smape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    denom = (np.abs(y_true) + np.abs(y_pred)) / 2
    mask = denom != 0
    return float(np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom[mask]) * 100)


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
