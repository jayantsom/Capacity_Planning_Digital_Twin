"""
Priority 3 — OEE Degradation Risk
==================================
XGBoost estimates future OEE degradation. It does not claim equipment failure
because the source has no work-order or failure labels.

Output tables:
  gold_maintenance_risk    — OEE degradation probability per equipment×site×test_type×month
  gold_maintenance_alerts  — HIGH/CRITICAL risk rows
"""

import warnings

import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from sklearn.metrics import average_precision_score, precision_recall_fscore_support, roc_auc_score
from xgboost import XGBClassifier

from capacity_twin_core.logging import logger as log
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

FAILURE_THRESHOLD_OEE = 0.88
HORIZON_MONTHS = 3
HIGH_RISK_THRESHOLD = 0.40

XGB_PARAMS = {
    "n_estimators": 300,
    "learning_rate": 0.05,
    "max_depth": 5,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 3,
    "scale_pos_weight": 5,
    "eval_metric": "aucpr",
    "random_state": 42,
    "n_jobs": -1,
}

OEE_LAG_COLS = [1, 2, 3, 6]
OEE_ROLL_COLS = [3, 6]


def attach_equipment_ids(feature_rows: pd.DataFrame, gcm: pd.DataFrame) -> pd.DataFrame:
    """Expand product rows only across explicitly qualified equipment IDs."""
    keys = ["site_id", "product_id", "test_type_id", "month", "snapshot_id"]
    mapping = (
        gcm[
            [
                "site_code",
                "product_number",
                "test_type",
                "month_key",
                "snapshot_id",
                "equipment_id",
            ]
        ]
        .rename(
            columns={
                "site_code": "site_id",
                "product_number": "product_id",
                "test_type": "test_type_id",
                "month_key": "month",
            }
        )
        .drop_duplicates(keys + ["equipment_id"])
    )
    expanded = feature_rows.drop(columns=["equipment_id"], errors="ignore").merge(
        mapping,
        on=keys,
        how="left",
        validate="one_to_many",
    )
    expanded["equipment_id"] = expanded["equipment_id"].fillna(
        expanded["site_id"].astype(str) + "|" + expanded["test_type_id"].astype(str)
    )
    return expanded


def aggregate_equipment_grain(df: pd.DataFrame) -> pd.DataFrame:
    """Remove product fan-out before equipment risk is calculated."""
    work = df.copy()
    if "equipment_id" not in work:
        work["equipment_id"] = work["site_id"].astype(str) + "|" + work["test_type_id"].astype(str)
    keys = ["equipment_id", "site_id", "test_type_id", "month"]
    # Product demand is additive, but snapshots/test fan-out are not.
    product_keys = keys + ["product_id"]
    product_month = (
        work.sort_values(product_keys)
        .groupby(product_keys, as_index=False)
        .agg(
            demand=("demand", "first"),
            avg_yield=("measured_yield", "mean"),
            avg_oee=("avg_oee", "mean"),
        )
    )
    return (
        product_month.groupby(keys, as_index=False)
        .agg(demand=("demand", "sum"), avg_yield=("avg_yield", "mean"), avg_oee=("avg_oee", "mean"))
        .sort_values(keys)
        .reset_index(drop=True)
    )


def generate_failure_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Label future OEE degradation, not unobserved equipment failure."""
    groups = ["equipment_id", "site_id", "test_type_id"]
    df = df.sort_values(groups + ["month"]).copy()
    df["degradation_label"] = np.nan

    for _, grp in df.groupby(groups):
        oee_vals = grp["avg_oee"].values
        labels = np.full(len(oee_vals), np.nan)
        for i in range(max(0, len(oee_vals) - HORIZON_MONTHS)):
            window = oee_vals[i + 1 : i + 1 + HORIZON_MONTHS]
            labels[i] = int(np.any(window < FAILURE_THRESHOLD_OEE))
        df.loc[grp.index, "degradation_label"] = labels

    pos_rate = df["degradation_label"].dropna().mean() * 100
    log.info(f"  OEE degradation positive rate: {pos_rate:.1f}%")
    return df


def build_maintenance_features(df: pd.DataFrame) -> pd.DataFrame:
    groups = ["equipment_id", "site_id", "test_type_id"]
    df = df.sort_values(groups + ["month"]).copy()
    df["month_of_year"] = df["month"] % 100
    df["year"] = df["month"] // 100

    for col in ["avg_oee", "avg_yield", "demand"]:
        if col in df.columns:
            df = add_lag_features(df, col, OEE_LAG_COLS, groups)
            df = add_rolling_features(df, col, OEE_ROLL_COLS, groups)

    # OEE trend vs 3 months ago
    df["oee_trend_3m"] = (
        df["avg_oee"] - df.groupby(groups)["avg_oee"].transform(lambda s: s.shift(3))
    ).fillna(0)

    return df


def _feat_cols(df: pd.DataFrame) -> list[str]:
    exclude = {
        "degradation_label",
        "failure_label",
        "month",
        "snapshot_id",
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
        "demand",
        "avg_yield",
        "avg_oee",
    }
    return [
        c
        for c in df.columns
        if c not in exclude and df[c].dtype in [np.float64, np.int64, np.int32, float, int]
    ]


def resample_training_fold(
    X: np.ndarray,
    y: np.ndarray,
    *,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply SMOTE only to one training fold; never to validation/holdout."""
    counts = np.bincount(y.astype(int), minlength=2)
    if counts.min() < 2:
        return X, y
    k_neighbors = min(5, int(counts.min()) - 1)
    return SMOTE(random_state=random_state, k_neighbors=k_neighbors).fit_resample(X, y)


def train_maintenance_model(df: pd.DataFrame):
    """Train with a blocked holdout and fold-local resampling."""
    feat_cols = _feat_cols(df)
    if not feat_cols:
        raise ValueError("OEE degradation risk is not evaluable: no safe numeric features")
    train, validation, holdout = temporal_split(
        df, holdout_months=3, validation_months=3, minimum_train_months=6
    )
    for split_name, split in (
        ("training", train),
        ("validation", validation),
        ("holdout", holdout),
    ):
        if split["degradation_label"].nunique() < 2:
            raise ValueError(
                f"OEE degradation risk is not evaluable: {split_name} labels have one class"
            )

    X_train = train[feat_cols].fillna(0).values
    y_train = train["degradation_label"].values
    X_res, y_res = resample_training_fold(X_train, y_train)
    selection = XGBClassifier(**XGB_PARAMS)
    selection.fit(X_res, y_res)
    validation_prob = selection.predict_proba(validation[feat_cols].fillna(0).values)[:, 1]
    validation_auc_pr = average_precision_score(validation["degradation_label"], validation_prob)

    fit_rows = pd.concat([train, validation], ignore_index=True)
    X_fit, y_fit = resample_training_fold(
        fit_rows[feat_cols].fillna(0).values,
        fit_rows["degradation_label"].values,
    )
    model = XGBClassifier(**XGB_PARAMS)
    model.fit(X_fit, y_fit)
    holdout_prob = model.predict_proba(holdout[feat_cols].fillna(0).values)[:, 1]
    y_holdout = holdout["degradation_label"].values
    holdout_pred = (holdout_prob >= HIGH_RISK_THRESHOLD).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_holdout, holdout_pred, average="binary", zero_division=0
    )
    metrics = {
        "validation_auc_pr": round(float(validation_auc_pr), 4),
        "holdout_auc_pr": round(float(average_precision_score(y_holdout, holdout_prob)), 4),
        "naive_auc_pr": round(float(np.mean(y_holdout)), 4),
        "holdout_precision": round(float(precision), 4),
        "holdout_recall": round(float(recall), 4),
        "holdout_f1": round(float(f1), 4),
        "holdout_roc_auc": (
            round(float(roc_auc_score(y_holdout, holdout_prob)), 4)
            if np.unique(y_holdout).size == 2
            else None
        ),
        "train_window": [int(train["month"].min()), int(train["month"].max())],
        "validation_window": [
            int(validation["month"].min()),
            int(validation["month"].max()),
        ],
        "holdout_window": [int(holdout["month"].min()), int(holdout["month"].max())],
    }
    split_roles = pd.Series("train", index=df.index, dtype="string")
    split_roles.loc[validation.index] = "validation"
    split_roles.loc[holdout.index] = "holdout"
    log.info(
        f"  Holdout AUC-PR: {metrics['holdout_auc_pr']:.4f} | naive: {metrics['naive_auc_pr']:.4f}"
    )
    return model, feat_cols, metrics, split_roles


def run_predictive_maintenance() -> dict:
    conn = get_conn()
    log.info("Loading feature store...")
    features = attach_equipment_ids(
        load_feature_store(conn),
        load_table(conn, "gold_gcm_base"),
    )
    fs = aggregate_equipment_grain(features)
    fs = fs[fs["avg_oee"].notna()].copy()

    log.info("Generating failure labels...")
    fs = generate_failure_labels(fs)

    log.info("Building maintenance features...")
    fs_feat = build_maintenance_features(fs)

    log.info("Training XGBoost maintenance classifier...")
    labeled = fs_feat[fs_feat["degradation_label"].notna()].copy()
    model, feat_cols, metrics, split_roles = train_maintenance_model(labeled)
    save_model(model, "maintenance_xgb", {"feature_schema": feat_cols, **metrics})

    available = [c for c in feat_cols if c in fs_feat.columns]
    fs_feat["degradation_prob"] = model.predict_proba(fs_feat[available].fillna(0).values)[:, 1]
    fs_feat["split_role"] = "future_inference"
    fs_feat.loc[split_roles.index, "split_role"] = split_roles
    fs_feat["risk_tier"] = pd.cut(
        fs_feat["degradation_prob"],
        bins=[0, 0.20, HIGH_RISK_THRESHOLD, 0.70, 1.01],
        labels=["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    )

    risk_df = fs_feat[
        [
            "equipment_id",
            "site_id",
            "test_type_id",
            "month",
            "avg_oee",
            "degradation_label",
            "degradation_prob",
            "risk_tier",
            "split_role",
        ]
    ].copy()
    if risk_df.duplicated(["equipment_id", "site_id", "test_type_id", "month"]).any():
        raise ValueError("Maintenance risk contains duplicate equipment-grain rows")
    risk_df["degradation_prob"] = risk_df["degradation_prob"].round(4)
    # Compatibility aliases remain explicit about the corrected semantics.
    risk_df["failure_label"] = risk_df["degradation_label"]
    risk_df["failure_prob"] = risk_df["degradation_prob"]

    alerts_df = risk_df[risk_df["risk_tier"].isin(["HIGH", "CRITICAL"])].copy()
    alerts_df["alert_generated_at"] = pd.Timestamp.utcnow().isoformat()

    n_risk = upsert_table(conn, risk_df, "gold_maintenance_risk")
    n_alerts = upsert_table(conn, alerts_df, "gold_maintenance_alerts")
    conn.close()

    log.info(f"  Wrote gold_maintenance_risk: {n_risk:,} rows")
    log.info(f"  Wrote gold_maintenance_alerts: {n_alerts:,} HIGH/CRITICAL alerts")

    return {
        "summary": f"{n_risk:,} OEE degradation scores | {n_alerts:,} alerts | holdout AUC-PR {metrics['holdout_auc_pr']:.4f}",
        "risk_rows": n_risk,
        "alert_rows": n_alerts,
        **metrics,
    }
