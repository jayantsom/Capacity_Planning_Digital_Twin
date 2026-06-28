"""
Priority 3 — Predictive Maintenance
=====================================
XGBoost binary classifier predicts equipment failure risk within 3 months.
Failure signal: OEE (oee_pct from gold_oee_metrics, normalised to avg_oee) < 65%.
SMOTE handles class imbalance.

Output tables:
  gold_maintenance_risk    — failure probability per site×test_type×month
  gold_maintenance_alerts  — HIGH/CRITICAL risk rows
"""

import warnings

import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

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

FAILURE_THRESHOLD_OEE = 0.88
HORIZON_MONTHS        = 3
HIGH_RISK_THRESHOLD   = 0.40
CV_FOLDS              = 5

XGB_PARAMS = dict(n_estimators=300, learning_rate=0.05, max_depth=5,
                  subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
                  scale_pos_weight=5, eval_metric="aucpr",
                  random_state=42, n_jobs=-1)

OEE_LAG_COLS  = [1, 2, 3, 6]
OEE_ROLL_COLS = [3, 6]


def generate_failure_labels(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["site_id", "test_type_id", "month"]).copy()
    df["failure_label"] = 0

    for (site, tt), grp in df.groupby(["site_id", "test_type_id"]):
        oee_vals = grp["avg_oee"].values
        labels   = np.zeros(len(oee_vals), dtype=int)
        for i in range(len(oee_vals) - 1):
            window = oee_vals[i + 1: i + 1 + HORIZON_MONTHS]
            if len(window) > 0 and np.any(window < FAILURE_THRESHOLD_OEE):
                labels[i] = 1
        df.loc[grp.index, "failure_label"] = labels

    pos_rate = df["failure_label"].mean() * 100
    log.info(f"  Failure label positive rate: {pos_rate:.1f}%")
    return df


def build_maintenance_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("month").copy()
    df["month_of_year"] = df["month"] % 100
    df["year"]          = df["month"] // 100

    for col in ["avg_oee", "avg_yield", "demand"]:
        if col in df.columns:
            df = add_lag_features(df, col, OEE_LAG_COLS)
            df = add_rolling_features(df, col, OEE_ROLL_COLS)

    # OEE trend vs 3 months ago
    df["oee_trend_3m"] = (
        df["avg_oee"]
        - df.groupby(["site_id", "test_type_id"])["avg_oee"]
          .transform(lambda s: s.shift(3))
    ).fillna(0)

    for col in ["site_id", "product_id", "test_type_id"]:
        if col in df.columns:
            le = LabelEncoder()
            df[col + "_enc"] = le.fit_transform(df[col].astype(str))

    return df


def _feat_cols(df: pd.DataFrame) -> list[str]:
    exclude = {"failure_label", "month", "snapshot_id", "feat_pk",
               "site_id", "product_id", "test_type_id",
               "platform_id", "family_id", "product_status",
               "region", "supplier_name", "demand", "avg_yield", "avg_oee"}
    return [c for c in df.columns
            if c not in exclude
            and df[c].dtype in [np.float64, np.int64, np.int32, float, int]]


def train_maintenance_model(df: pd.DataFrame):
    feat_cols = _feat_cols(df)
    X = df[feat_cols].fillna(0).values
    y = df["failure_label"].values

    log.info(f"  Class dist — 0: {(y==0).sum():,}  1: {(y==1).sum():,}")

    k_neighbors = min(5, max(1, (y == 1).sum() - 1))
    smote   = SMOTE(random_state=42, k_neighbors=k_neighbors)
    X_res, y_res = smote.fit_resample(X, y)
    log.info(f"  After SMOTE — 0: {(y_res==0).sum():,}  1: {(y_res==1).sum():,}")

    cv_auc_prs = []
    skf = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=42)
    for tr, val in skf.split(X_res, y_res):
        m = XGBClassifier(**XGB_PARAMS)
        m.fit(X_res[tr], y_res[tr])
        cv_auc_prs.append(
            average_precision_score(y_res[val], m.predict_proba(X_res[val])[:, 1])
        )
    cv_auc_pr = float(np.mean(cv_auc_prs))

    model = XGBClassifier(**XGB_PARAMS)
    model.fit(X_res, y_res)

    proba_all = model.predict_proba(X)[:, 1]
    metrics = {"cv_auc_pr":     round(cv_auc_pr, 4),
               "train_roc_auc": round(roc_auc_score(y, proba_all), 4),
               "train_auc_pr":  round(average_precision_score(y, proba_all), 4)}
    log.info(f"  CV AUC-PR: {cv_auc_pr:.4f} | Train ROC-AUC: {metrics['train_roc_auc']:.4f}")
    return model, feat_cols, metrics


def run_predictive_maintenance() -> dict:
    conn = get_conn()
    log.info("Loading feature store...")
    fs = load_feature_store(conn)
    fs = fs[fs["avg_oee"].notna()].copy()

    log.info("Generating failure labels...")
    fs = generate_failure_labels(fs)

    log.info("Building maintenance features...")
    fs_feat = build_maintenance_features(fs)

    log.info("Training XGBoost maintenance classifier...")
    model, feat_cols, metrics = train_maintenance_model(fs_feat)
    save_model(model, "maintenance_xgb", {"features": feat_cols, **metrics})

    available = [c for c in feat_cols if c in fs_feat.columns]
    fs_feat["failure_prob"] = model.predict_proba(fs_feat[available].fillna(0).values)[:, 1]
    fs_feat["risk_tier"]    = pd.cut(
        fs_feat["failure_prob"],
        bins=[0, 0.20, HIGH_RISK_THRESHOLD, 0.70, 1.01],
        labels=["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    )

    risk_df = fs_feat[["site_id", "test_type_id", "month",
                        "avg_oee", "failure_label", "failure_prob", "risk_tier"]].copy()
    risk_df["failure_prob"] = risk_df["failure_prob"].round(4)

    alerts_df = risk_df[risk_df["risk_tier"].isin(["HIGH", "CRITICAL"])].copy()
    alerts_df["alert_generated_at"] = pd.Timestamp.utcnow().isoformat()

    n_risk   = upsert_table(conn, risk_df,   "gold_maintenance_risk")
    n_alerts = upsert_table(conn, alerts_df, "gold_maintenance_alerts")
    conn.close()

    log.info(f"  Wrote gold_maintenance_risk: {n_risk:,} rows")
    log.info(f"  Wrote gold_maintenance_alerts: {n_alerts:,} HIGH/CRITICAL alerts")

    return {"summary": f"{n_risk:,} risk scores | {n_alerts:,} alerts | CV AUC-PR {metrics['cv_auc_pr']:.4f}",
            "risk_rows": n_risk, "alert_rows": n_alerts, **metrics}
