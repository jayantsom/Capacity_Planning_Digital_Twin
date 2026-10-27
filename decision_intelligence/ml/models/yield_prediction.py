"""
Priority 2 — Yield Prediction
================================
XGBoost regressor predicts first-pass yield per test_type × product × site.
SHAP values explain which process factors drive yield loss.
Predictions feed back into capacity math as gold_cap_ml_adjusted.

Internal names (post normalisation): product_id, site_id, test_type_id,
month (int yyyymm), avg_yield, avg_oee, demand.

gcm_base raw column names used directly for capacity recalculation.

Output tables:
  gold_yield_predictions    — ML yield per product×site×test_type×month
  gold_yield_shap           — Top-N SHAP drivers per prediction
  gold_cap_ml_adjusted      — Capacity recalculated with ML yield
"""

import warnings

import numpy as np
import pandas as pd
import shap
from sklearn.metrics import r2_score
from xgboost import XGBRegressor

from capacity_twin_core.logging import logger as log
from decision_intelligence.ml_support import (
    add_lag_features,
    add_rolling_features,
    get_conn,
    load_feature_store,
    load_table,
    metric_result,
    save_model,
    temporal_split,
    upsert_table,
)

warnings.filterwarnings("ignore")

TARGET = "measured_yield"
SERIES_COLS = ["site_id", "product_id", "test_type_id", "planning_version_id"]
LAG_COLS = [1, 2, 3, 6]
ROLL_COLS = [3, 6]
TOP_SHAP = 10

# Capacity math constants (Step 3 — adjusted)
ALLOWANCE = 0.10
PRODUCTIVITY = 0.95

XGB_PARAMS = {
    "n_estimators": 400,
    "learning_rate": 0.04,
    "max_depth": 7,
    "subsample": 0.8,
    "colsample_bytree": 0.7,
    "min_child_weight": 5,
    "reg_alpha": 0.05,
    "reg_lambda": 1.5,
    "random_state": 42,
    "n_jobs": -1,
}

EXCLUDE = {
    TARGET,
    "month",
    "planning_version_id",
    "feat_pk",
    "feature_row_id",
    "site_id",
    "product_id",
    "test_type_id",
    "platform_id",
    "family_id",
    "product_status",
    "region",
    "supplier_name",
    "demand",
    "avg_oee",
    "availability",
    "performance",
    "quality",
    "is_actual",
    "data_type",
}


def build_yield_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build trailing features without including the row's measured yield."""
    df = df.sort_values(SERIES_COLS + ["month"]).copy()
    df["month_of_year"] = df["month"] % 100
    df["year"] = df["month"] // 100
    df["quarter"] = ((df["month_of_year"] - 1) // 3) + 1

    for col in [TARGET, "avg_oee", "demand"]:
        if col in df.columns:
            df = add_lag_features(df, col, LAG_COLS, SERIES_COLS)
            df = add_rolling_features(df, col, ROLL_COLS, SERIES_COLS)
    return df


def _feat_cols(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in df.columns
        if c not in EXCLUDE and df[c].dtype in [np.float64, np.int64, np.int32, float, int]
    ]


def train_yield_model(df: pd.DataFrame):
    """Select on past months and reserve the final months as untouched holdout."""
    if df[TARGET].nunique(dropna=True) < 2:
        raise ValueError("Yield prediction is not evaluable: measured yield is constant")
    feat_cols = _feat_cols(df)
    if not feat_cols:
        raise ValueError("Yield prediction is not evaluable: no safe numeric features")
    train, validation, holdout = temporal_split(
        df, holdout_months=3, validation_months=3, minimum_train_months=6
    )
    selection_model = XGBRegressor(**XGB_PARAMS)
    selection_model.fit(train[feat_cols].fillna(0), train[TARGET].clip(0, 1))
    validation_pred = selection_model.predict(validation[feat_cols].fillna(0)).clip(0, 1)
    validation_naive = validation[f"{TARGET}_lag1"].fillna(train[TARGET].median())
    validation_metrics = metric_result(
        validation[TARGET], validation_pred, naive_pred=validation_naive
    )

    fit_rows = pd.concat([train, validation], ignore_index=True)
    model = XGBRegressor(**XGB_PARAMS)
    model.fit(fit_rows[feat_cols].fillna(0), fit_rows[TARGET].clip(0, 1))
    holdout_pred = model.predict(holdout[feat_cols].fillna(0)).clip(0, 1)
    holdout_naive = holdout[f"{TARGET}_lag1"].fillna(fit_rows[TARGET].median())
    holdout_metrics = metric_result(holdout[TARGET], holdout_pred, naive_pred=holdout_naive)
    metrics = {
        "validation_mae": round(float(validation_metrics["mae"]), 6),
        "holdout_mae": round(float(holdout_metrics["mae"]), 6),
        "holdout_mae_pp": round(float(holdout_metrics["mae"]) * 100, 3),
        "naive_holdout_mae": round(float(holdout_metrics["naive_mae"]), 6),
        "beats_naive_mae": holdout_metrics["beats_naive_mae"],
        "holdout_r2": (
            round(float(r2_score(holdout[TARGET], holdout_pred)), 4)
            if holdout[TARGET].nunique() > 1
            else None
        ),
        "train_window": [int(train["month"].min()), int(train["month"].max())],
        "validation_window": [int(validation["month"].min()), int(validation["month"].max())],
        "holdout_window": [int(holdout["month"].min()), int(holdout["month"].max())],
    }
    split_roles = pd.Series("train", index=df.index)
    split_roles.loc[validation.index] = "validation"
    split_roles.loc[holdout.index] = "holdout"
    log.info(
        f"  Yield holdout MAE: {metrics['holdout_mae_pp']:.2f}pp "
        f"| naive: {metrics['naive_holdout_mae'] * 100:.2f}pp"
    )
    return model, feat_cols, metrics, split_roles


def compute_shap(model, X: pd.DataFrame, feat_cols: list[str]) -> pd.DataFrame:
    log.info(f"  Computing SHAP for {len(X):,} rows...")
    explainer = shap.TreeExplainer(model)
    shap_vals = explainer.shap_values(X[feat_cols].fillna(0))
    shap_df = pd.DataFrame(shap_vals, columns=feat_cols, index=X.index)

    records = []
    row_positions = {index: position for position, index in enumerate(X.index)}
    for idx, row in shap_df.iterrows():
        top = row.abs().nlargest(TOP_SHAP)
        for feat, importance in top.items():
            records.append(
                {
                    "feature_row_id": X.loc[idx, "feature_row_id"],
                    "row_idx": row_positions[idx],
                    "feature": feat,
                    "shap_value": round(float(row[feat]), 6),
                    "abs_shap": round(float(importance), 6),
                }
            )
    return pd.DataFrame(records)


def recalculate_capacity_with_ml_yield(conn, yield_pred_df: pd.DataFrame) -> pd.DataFrame:
    """
    Fetch gold_gcm_base (raw column names), merge ML yield, rerun Steps 1-5.
    Uses gcm_base raw names: target_yield, handling_time_sec, target_test_time_sec,
    yield_retest_1, retest_quote, utilization_rate, hours_per_shift_normal,
    allowance_pct, productivity_pct, working_days_normal, shifts_per_day_normal,
    equip_qty_available, effective_demand_qty.
    """
    gcm = load_table(conn, "gold_gcm_base")

    # yield_pred_df uses internal names; map back to gcm join keys
    join_cols = ["product_id", "site_id", "test_type_id", "month", "planning_version_id"]
    if yield_pred_df.duplicated(join_cols).any():
        raise ValueError("Yield predictions are not unique at their declared grain")
    ml_yield = yield_pred_df[join_cols + ["predicted_yield"]].rename(
        columns={
            "product_id": "product_number",
            "site_id": "site_code",
            "test_type_id": "test_type",
            "month": "month_key",
        }
    )
    before = len(gcm)
    gcm = gcm.merge(
        ml_yield,
        on=["product_number", "site_code", "test_type", "month_key", "planning_version_id"],
        how="left",
        validate="many_to_one",
    )
    if len(gcm) != before:
        raise ValueError("Planning version-aware yield merge changed capacity row count")
    gcm["yield_used"] = gcm["predicted_yield"].fillna(gcm["target_yield"])

    # Step 1 — Type1 retest (retest_times=2, test_x_param=0.75)
    retest_times = 2.0
    test_x_param = 0.75
    gcm["step1"] = (gcm["handling_time_sec"] + gcm["target_test_time_sec"]) * (
        1 + (1 - gcm["yield_used"]) * retest_times * test_x_param
    )
    # Step 2
    gcm["step2"] = gcm["step1"] / gcm["utilization_rate"].replace(0, np.nan)
    # Step 3 (adjusted) — use allowance_pct / productivity_pct from gcm
    gcm["step3"] = (
        gcm["hours_per_shift_normal"] * 3600 * (1 - gcm["allowance_pct"]) * gcm["productivity_pct"]
    ) / gcm["step2"].replace(0, np.nan)
    # Step 4
    gcm["step4"] = gcm["working_days_normal"] * gcm["shifts_per_day_normal"]
    # Step 5
    gcm["supply_ml"] = gcm["equip_qty_available"] * gcm["step3"] * gcm["step4"]
    gcm["utilization_ratio_ml"] = (
        (gcm["effective_demand_qty"] / gcm["supply_ml"].replace(0, np.nan)).fillna(0).clip(0, 5)
    )
    gcm["capacity_gap_ratio_ml"] = (
        (gcm["supply_ml"] - gcm["effective_demand_qty"])
        / gcm["effective_demand_qty"].replace(0, np.nan)
    ).fillna(0)
    gcm["capacity_gap_pct_ml"] = gcm["capacity_gap_ratio_ml"] * 100

    keep = [
        "product_number",
        "site_code",
        "test_type",
        "month_key",
        "planning_version_id",
        "yield_used",
        "target_yield",
        "step1",
        "step2",
        "step3",
        "step4",
        "supply_ml",
        "utilization_ratio_ml",
        "capacity_gap_ratio_ml",
        "capacity_gap_pct_ml",
        "effective_demand_qty",
        "equip_qty_available",
    ]
    return gcm[[c for c in keep if c in gcm.columns]]


def run_yield_prediction() -> dict:
    conn = get_conn()
    log.info("Loading feature store for yield prediction...")
    fs = load_feature_store(conn)
    fs = fs[fs[TARGET].notna() & fs[TARGET].between(0, 1)].copy()
    if fs.empty:
        raise ValueError("No measured production yield is available; target yield is not a label")
    log.info(f"  Training rows: {len(fs):,}")

    log.info("Building features...")
    fs_feat = build_yield_features(fs)

    log.info("Training yield XGBoost model...")
    model, feat_cols, metrics, split_roles = train_yield_model(fs_feat)
    save_model(model, "yield_xgb", {"feature_schema": feat_cols, **metrics})

    X_all = fs_feat[feat_cols].fillna(0)
    fs_feat["predicted_yield"] = model.predict(X_all).clip(0.01, 1.0)
    fs_feat["split_role"] = split_roles
    yield_pred_df = fs_feat[
        [
            "feature_row_id",
            "product_id",
            "site_id",
            "test_type_id",
            "month",
            "planning_version_id",
            TARGET,
            "target_yield",
            "predicted_yield",
            "split_role",
        ]
    ].copy()
    yield_pred_df["row_idx"] = np.arange(len(yield_pred_df), dtype=int)
    yield_pred_df["yield_residual"] = yield_pred_df["predicted_yield"] - yield_pred_df[TARGET]
    yield_pred_df["abs_error_pp"] = (yield_pred_df["yield_residual"].abs() * 100).round(3)

    log.info("Computing SHAP explanations...")
    shap_df = compute_shap(model, fs_feat, feat_cols)

    log.info("Recalculating capacity with ML yield...")
    cap_ml_df = recalculate_capacity_with_ml_yield(conn, yield_pred_df)

    n_yp = upsert_table(conn, yield_pred_df, "gold_yield_predictions")
    n_sh = upsert_table(conn, shap_df, "gold_yield_shap")
    n_cap = upsert_table(conn, cap_ml_df, "gold_cap_ml_adjusted")
    conn.close()

    log.info(f"  Wrote gold_yield_predictions: {n_yp:,} rows")
    log.info(f"  Wrote gold_yield_shap: {n_sh:,} rows")
    log.info(f"  Wrote gold_cap_ml_adjusted: {n_cap:,} rows")

    return {
        "summary": f"{n_yp:,} yield predictions | holdout MAE {metrics['holdout_mae_pp']:.2f}pp",
        "yield_prediction_rows": n_yp,
        "shap_rows": n_sh,
        "cap_ml_adjusted_rows": n_cap,
        **metrics,
    }
