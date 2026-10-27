"""
Priority 4 — OEE Anomaly Detection
=====================================
Unsupervised Isolation Forest on avg_oee (normalised from oee_pct).

Output tables:
  gold_oee_anomalies         — anomaly scores + flag per row
  gold_oee_anomaly_summary   — anomaly rate per site
"""

import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from capacity_twin_core.logging import logger as log
from decision_intelligence.ml.models.predictive_maintenance import (
    aggregate_equipment_grain,
    attach_equipment_ids,
)
from decision_intelligence.ml_support import (
    add_lag_features,
    add_rolling_features,
    get_conn,
    load_feature_store,
    load_table,
    save_model,
    temporal_split,
    upsert_table,
)

warnings.filterwarnings("ignore")

CONTAMINATION = 0.05
IF_N_ESTIMATORS = 200
IF_RANDOM_STATE = 42

OEE_COMPONENTS = ["avg_oee", "avg_yield", "demand"]
LAG_COLS = [1, 2, 3]
ROLL_COLS = [3, 6]


def build_oee_features(df: pd.DataFrame) -> pd.DataFrame:
    groups = ["equipment_id", "site_id", "test_type_id"]
    df = df.sort_values(groups + ["month"]).copy()
    df["month_of_year"] = df["month"] % 100
    df["year"] = df["month"] // 100

    for col in OEE_COMPONENTS:
        if col in df.columns:
            df = add_lag_features(df, col, LAG_COLS, groups)
            df = add_rolling_features(df, col, ROLL_COLS, groups)

    for col in OEE_COMPONENTS:
        if col in df.columns:
            df[f"{col}_vol_3m"] = (
                df.groupby(groups)[col]
                .transform(lambda s: s.shift(1).rolling(3, min_periods=1).std())
                .fillna(0)
            )

    if "avg_oee" in df.columns:
        site_mean = df.groupby("site_id")["avg_oee"].transform(
            lambda values: values.shift(1).expanding().mean()
        )
        df["oee_deviation_from_site"] = df["avg_oee"] - site_mean

    return df


def _feat_cols(df: pd.DataFrame) -> list[str]:
    exclude = {
        "month",
        "planning_version_id",
        "feat_pk",
        "feature_row_id",
        "equipment_id",
        "site_id",
        "product_id",
        "test_type_id",
        "platform_id",
        "family_id",
        "product_status",
        "region",
        "supplier_name",
    }
    return [
        c
        for c in df.columns
        if c not in exclude
        and df[c].dtype in [np.float64, np.int64, np.int32, float, int]
        and df[c].notna().sum() > 0
    ]


def calibrate_severity_thresholds(train_scores: np.ndarray) -> dict[str, float]:
    """Freeze absolute severity cutoffs from historical training scores."""
    return {
        "critical": float(np.quantile(train_scores, 0.02)),
        "high": float(np.quantile(train_scores, 0.05)),
        "medium": float(np.quantile(train_scores, 0.10)),
    }


def assign_severity(scores: pd.Series, thresholds: dict[str, float]) -> pd.Series:
    """Assign stable labels without ranking the scored batch."""
    conditions = [
        scores <= thresholds["critical"],
        scores <= thresholds["high"],
        scores <= thresholds["medium"],
    ]
    return pd.Series(
        np.select(conditions, ["CRITICAL", "HIGH", "MEDIUM"], default="NORMAL"),
        index=scores.index,
        dtype="string",
    )


def run_oee_anomaly() -> dict:
    conn = get_conn()
    log.info("Loading OEE data from feature store...")
    features = attach_equipment_ids(
        load_feature_store(conn),
        load_table(conn, "gold_gcm_base"),
    )
    fs = aggregate_equipment_grain(features)
    fs = fs[fs["avg_oee"].notna()].copy()
    log.info(f"  OEE rows: {len(fs):,}")

    log.info("Building OEE features...")
    fs_feat = build_oee_features(fs)

    feat_cols = _feat_cols(fs_feat)
    train, _, holdout = temporal_split(
        fs_feat, holdout_months=3, validation_months=3, minimum_train_months=6
    )
    X_train = train[feat_cols].fillna(0).values
    X_holdout = holdout[feat_cols].fillna(0).values
    log.info(f"  Training matrix: {X_train.shape}; holdout: {X_holdout.shape}")

    log.info("Training Isolation Forest...")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)

    iso = IsolationForest(
        n_estimators=IF_N_ESTIMATORS,
        contamination=CONTAMINATION,
        random_state=IF_RANDOM_STATE,
        n_jobs=-1,
    )
    iso.fit(X_train_scaled)
    train_scores = iso.score_samples(X_train_scaled)
    severity_thresholds = calibrate_severity_thresholds(train_scores)
    save_model(
        {"isolation_forest": iso, "scaler": scaler},
        "oee_isolation_forest",
        {
            "contamination": CONTAMINATION,
            "feature_schema": feat_cols,
            "severity_thresholds": severity_thresholds,
            "train_window": [int(train["month"].min()), int(train["month"].max())],
            "holdout_window": [int(holdout["month"].min()), int(holdout["month"].max())],
        },
    )

    scored = holdout.copy()
    holdout_scaled = scaler.transform(X_holdout)
    scored["anomaly_score"] = iso.score_samples(holdout_scaled)
    scored["anomaly_flag"] = (scored["anomaly_score"] <= severity_thresholds["medium"]).astype(int)
    scored["anomaly_severity"] = assign_severity(scored["anomaly_score"], severity_thresholds)
    z_values = np.abs(holdout_scaled)
    driver_indexes = np.argmax(z_values, axis=1)
    scored["anomaly_driver"] = [feat_cols[index] for index in driver_indexes]
    scored["split_role"] = "holdout"

    anomaly_df = scored[
        [
            "equipment_id",
            "site_id",
            "test_type_id",
            "month",
            "avg_oee",
            "anomaly_score",
            "anomaly_flag",
            "anomaly_severity",
            "anomaly_driver",
            "split_role",
        ]
    ].copy()
    anomaly_df["anomaly_score"] = anomaly_df["anomaly_score"].round(6)

    summary_df = (
        anomaly_df.groupby("site_id")
        .agg(
            total_records=("anomaly_flag", "count"),
            anomaly_count=("anomaly_flag", "sum"),
            mean_oee=("avg_oee", "mean"),
            min_oee=("avg_oee", "min"),
        )
        .reset_index()
    )
    summary_df["anomaly_rate_pct"] = (
        summary_df["anomaly_count"] / summary_df["total_records"] * 100
    ).round(2)
    summary_df["mean_oee"] = summary_df["mean_oee"].round(4)
    summary_df["min_oee"] = summary_df["min_oee"].round(4)

    n_anom = upsert_table(conn, anomaly_df, "gold_oee_anomalies")
    n_summ = upsert_table(conn, summary_df, "gold_oee_anomaly_summary")
    conn.close()

    total_anomalies = int(anomaly_df["anomaly_flag"].sum())
    anomaly_rate = anomaly_df["anomaly_flag"].mean() * 100
    log.info(
        f"  Wrote gold_oee_anomalies: {n_anom:,} rows | {total_anomalies:,} flagged ({anomaly_rate:.1f}%)"
    )
    log.info(f"  Wrote gold_oee_anomaly_summary: {n_summ:,} sites")

    return {
        "summary": f"{n_anom:,} scored | {total_anomalies:,} anomalies ({anomaly_rate:.1f}%)",
        "scored_rows": n_anom,
        "anomaly_count": total_anomalies,
        "anomaly_rate_pct": round(anomaly_rate, 2),
        "summary_rows": n_summ,
    }
