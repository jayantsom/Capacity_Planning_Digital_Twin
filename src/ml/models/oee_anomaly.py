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

from src.utils.logger import logger as log
from src.utils.ml_utils import (
    add_lag_features,
    add_rolling_features,
    get_conn,
    load_feature_store,
    save_model,
    upsert_table,
)

warnings.filterwarnings("ignore")

CONTAMINATION  = 0.05
IF_N_ESTIMATORS = 200
IF_RANDOM_STATE = 42

OEE_COMPONENTS = ["avg_oee", "avg_yield", "demand"]
LAG_COLS  = [1, 2, 3]
ROLL_COLS = [3, 6]


def build_oee_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("month").copy()
    df["month_of_year"] = df["month"] % 100
    df["year"]          = df["month"] // 100

    for col in OEE_COMPONENTS:
        if col in df.columns:
            df = add_lag_features(df, col, LAG_COLS)
            df = add_rolling_features(df, col, ROLL_COLS)

    for col in OEE_COMPONENTS:
        if col in df.columns:
            df[f"{col}_vol_3m"] = (
                df.groupby(["site_id", "test_type_id"])[col]
                .transform(lambda s: s.rolling(3, min_periods=1).std())
                .fillna(0)
            )

    if "avg_oee" in df.columns:
        site_mean = df.groupby("site_id")["avg_oee"].transform("mean")
        df["oee_deviation_from_site"] = df["avg_oee"] - site_mean

    return df


def _feat_cols(df: pd.DataFrame) -> list[str]:
    exclude = {"month", "snapshot_id", "feat_pk", "site_id",
               "product_id", "test_type_id", "platform_id", "family_id",
               "product_status", "region", "supplier_name"}
    return [c for c in df.columns
            if c not in exclude
            and df[c].dtype in [np.float64, np.int64, np.int32, float, int]
            and df[c].notna().sum() > 0]


def run_oee_anomaly() -> dict:
    conn = get_conn()
    log.info("Loading OEE data from feature store...")
    fs = load_feature_store(conn)
    fs = fs[fs["avg_oee"].notna()].copy()
    log.info(f"  OEE rows: {len(fs):,}")

    log.info("Building OEE features...")
    fs_feat = build_oee_features(fs)

    feat_cols = _feat_cols(fs_feat)
    X = fs_feat[feat_cols].fillna(0).values
    log.info(f"  Feature matrix: {X.shape}")

    log.info("Training Isolation Forest...")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    iso = IsolationForest(n_estimators=IF_N_ESTIMATORS, contamination=CONTAMINATION,
                          random_state=IF_RANDOM_STATE, n_jobs=-1)
    iso.fit(X_scaled)
    save_model({"isolation_forest": iso, "scaler": scaler}, "oee_isolation_forest",
               {"contamination": CONTAMINATION, "features": feat_cols})

    fs_feat["anomaly_score"] = iso.score_samples(X_scaled)
    fs_feat["anomaly_flag"]  = (iso.predict(X_scaled) == -1).astype(int)

    score_pct = fs_feat["anomaly_score"].rank(pct=True)
    fs_feat["anomaly_severity"] = pd.cut(
        score_pct,
        bins=[0, 0.02, 0.05, 0.10, 1.01],
        labels=["CRITICAL", "HIGH", "MEDIUM", "NORMAL"],
    )

    anomaly_df = fs_feat[["site_id", "test_type_id", "month",
                           "avg_oee", "anomaly_score", "anomaly_flag",
                           "anomaly_severity"]].copy()
    anomaly_df["anomaly_score"] = anomaly_df["anomaly_score"].round(6)

    summary_df = (
        anomaly_df.groupby("site_id")
        .agg(total_records=("anomaly_flag", "count"),
             anomaly_count=("anomaly_flag", "sum"),
             mean_oee=("avg_oee", "mean"),
             min_oee=("avg_oee", "min"))
        .reset_index()
    )
    summary_df["anomaly_rate_pct"] = (
        summary_df["anomaly_count"] / summary_df["total_records"] * 100
    ).round(2)
    summary_df["mean_oee"] = summary_df["mean_oee"].round(4)
    summary_df["min_oee"]  = summary_df["min_oee"].round(4)

    n_anom = upsert_table(conn, anomaly_df, "gold_oee_anomalies")
    n_summ = upsert_table(conn, summary_df, "gold_oee_anomaly_summary")
    conn.close()

    total_anomalies = int(anomaly_df["anomaly_flag"].sum())
    anomaly_rate    = anomaly_df["anomaly_flag"].mean() * 100
    log.info(f"  Wrote gold_oee_anomalies: {n_anom:,} rows | {total_anomalies:,} flagged ({anomaly_rate:.1f}%)")
    log.info(f"  Wrote gold_oee_anomaly_summary: {n_summ:,} sites")

    return {"summary": f"{n_anom:,} scored | {total_anomalies:,} anomalies ({anomaly_rate:.1f}%)",
            "scored_rows": n_anom, "anomaly_count": total_anomalies,
            "anomaly_rate_pct": round(anomaly_rate, 2), "summary_rows": n_summ}
