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
from pyarrow import fs
import shap
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBRegressor

from src.utils.logger import logger as log
from src.utils.ml_utils import (
    add_lag_features,
    add_rolling_features,
    encode_categoricals,
    get_conn,
    load_feature_store,
    load_table,
    mape,
    rmse,
    save_model,
    upsert_table,
)

warnings.filterwarnings("ignore")

TARGET    = "avg_yield"
CAT_COLS  = ["site_id", "product_id", "platform_id", "family_id", "test_type_id"]
LAG_COLS  = [1, 2, 3, 6]
ROLL_COLS = [3, 6]
TOP_SHAP  = 10

# Capacity math constants (Step 3 — adjusted)
ALLOWANCE    = 0.10
PRODUCTIVITY = 0.95

XGB_PARAMS = dict(n_estimators=400, learning_rate=0.04, max_depth=7,
                  subsample=0.8, colsample_bytree=0.7, min_child_weight=5,
                  reg_alpha=0.05, reg_lambda=1.5, random_state=42, n_jobs=-1)

EXCLUDE = {TARGET, "month", "snapshot_id", "feat_pk",
           "product_status", "region", "supplier_name", "demand"}


def build_yield_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("month").copy()
    df["month_of_year"] = df["month"] % 100
    df["year"]          = df["month"] // 100
    df["quarter"]       = ((df["month_of_year"] - 1) // 3) + 1

    for col in [TARGET, "avg_oee", "demand"]:
        if col in df.columns:
            df = add_lag_features(df, col, LAG_COLS)
            df = add_rolling_features(df, col, ROLL_COLS)
    return df


def _feat_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns
            if c not in EXCLUDE
            and df[c].dtype in [np.float64, np.int64, np.int32, float, int]]


def train_yield_model(df: pd.DataFrame):
    feat_cols = _feat_cols(df)
    X = df[feat_cols].fillna(0)
    y = df[TARGET].clip(0, 1)

    tscv    = TimeSeriesSplit(n_splits=5)
    cv_maes = []
    for tr, val in tscv.split(X):
        m = XGBRegressor(**XGB_PARAMS)
        m.fit(X.iloc[tr], y.iloc[tr])
        cv_maes.append(mean_absolute_error(y.iloc[val],
                                           m.predict(X.iloc[val]).clip(0, 1)))

    cv_mae = float(np.mean(cv_maes))
    model  = XGBRegressor(**XGB_PARAMS)
    model.fit(X, y)
    metrics = {"cv_mae": round(cv_mae, 4),
               "cv_mae_pct": round(cv_mae * 100, 2),
               "train_r2": round(float(r2_score(y, model.predict(X).clip(0, 1))), 4)}
    log.info(f"  Yield model CV-MAE: {cv_mae*100:.2f}pp | Train R²: {metrics['train_r2']:.4f}")
    return model, feat_cols, metrics


def compute_shap(model, X: pd.DataFrame, feat_cols: list[str]) -> pd.DataFrame:
    log.info(f"  Computing SHAP for {len(X):,} rows...")
    explainer = shap.TreeExplainer(model)
    shap_vals = explainer.shap_values(X[feat_cols].fillna(0))
    shap_df   = pd.DataFrame(shap_vals, columns=feat_cols, index=X.index)

    records = []
    for idx, row in shap_df.iterrows():
        top = row.abs().nlargest(TOP_SHAP)
        for feat, importance in top.items():
            records.append({"row_idx": idx, "feature": feat,
                            "shap_value": round(float(row[feat]), 6),
                            "abs_shap": round(float(importance), 6)})
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
    ml_yield = yield_pred_df[["product_id", "site_id", "test_type_id", "month",
                               "predicted_yield"]].rename(columns={
        "product_id":  "product_number",
        "site_id":     "site_code",
        "test_type_id":"test_type",
        "month":       "month_key",
    })
    gcm = gcm.merge(ml_yield, on=["product_number", "site_code", "test_type", "month_key"],
                    how="left")
    gcm["yield_used"] = gcm["predicted_yield"].fillna(gcm["target_yield"])

    # Step 1 — Type1 retest (retest_times=2, test_x_param=0.75)
    retest_times  = 2.0
    test_x_param  = 0.75
    gcm["step1"]  = (gcm["handling_time_sec"] + gcm["target_test_time_sec"]) * (
        1 + (1 - gcm["yield_used"]) * retest_times * test_x_param
    )
    # Step 2
    gcm["step2"] = gcm["step1"] / gcm["utilization_rate"].replace(0, np.nan)
    # Step 3 (adjusted) — use allowance_pct / productivity_pct from gcm
    gcm["step3"] = (
        gcm["hours_per_shift_normal"] * 3600
        * (1 - gcm["allowance_pct"])
        * gcm["productivity_pct"]
    ) / gcm["step2"].replace(0, np.nan)
    # Step 4
    gcm["step4"] = gcm["working_days_normal"] * gcm["shifts_per_day_normal"]
    # Step 5
    gcm["supply_ml"]            = gcm["equip_qty_available"] * gcm["step3"] * gcm["step4"]
    gcm["utilization_ratio_ml"] = (gcm["effective_demand_qty"]
                                   / gcm["supply_ml"].replace(0, np.nan)).fillna(0).clip(0, 5)
    gcm["capacity_gap_pct_ml"]  = (
        (gcm["supply_ml"] - gcm["effective_demand_qty"])
        / gcm["effective_demand_qty"].replace(0, np.nan) * 100
    ).fillna(0)

    keep = ["product_number", "site_code", "test_type", "month_key",
            "yield_used", "target_yield",
            "step1", "step2", "step3", "step4",
            "supply_ml", "utilization_ratio_ml", "capacity_gap_pct_ml",
            "effective_demand_qty", "equip_qty_available"]
    return gcm[[c for c in keep if c in gcm.columns]]


def run_yield_prediction() -> dict:
    conn = get_conn()
    log.info("Loading feature store for yield prediction...")
    fs = load_feature_store(conn)
    fs = fs[fs[TARGET].notna() & (fs[TARGET] > 0)].copy()
    log.info(f"  Training rows: {len(fs):,}")

    log.info("Building features...")
    fs_feat = build_yield_features(fs)
    fs_feat = encode_categoricals(fs_feat, CAT_COLS)

    log.info("Training yield XGBoost model...")
    model, feat_cols, metrics = train_yield_model(fs_feat)
    save_model(model, "yield_xgb", {"features": feat_cols, **metrics})

    X_all = fs_feat[feat_cols].fillna(0)
    fs_feat["predicted_yield"] = model.predict(X_all).clip(0.01, 1.0)

    fs["predicted_yield"] = fs_feat["predicted_yield"].values
    yield_pred_df = fs[["product_id", "site_id", "test_type_id", "month", 
                        TARGET, "predicted_yield"]].copy()
    yield_pred_df["yield_residual"] = yield_pred_df["predicted_yield"] - yield_pred_df[TARGET]
    yield_pred_df["abs_error_pp"]   = (yield_pred_df["yield_residual"].abs() * 100).round(3)

    log.info("Computing SHAP explanations...")
    shap_df = compute_shap(model, fs_feat, feat_cols)

    log.info("Recalculating capacity with ML yield...")
    cap_ml_df = recalculate_capacity_with_ml_yield(conn, yield_pred_df)

    n_yp  = upsert_table(conn, yield_pred_df, "gold_yield_predictions")
    n_sh  = upsert_table(conn, shap_df,       "gold_yield_shap")
    n_cap = upsert_table(conn, cap_ml_df,     "gold_cap_ml_adjusted")
    conn.close()

    log.info(f"  Wrote gold_yield_predictions: {n_yp:,} rows")
    log.info(f"  Wrote gold_yield_shap: {n_sh:,} rows")
    log.info(f"  Wrote gold_cap_ml_adjusted: {n_cap:,} rows")

    return {"summary": f"{n_yp:,} yield predictions | CV-MAE {metrics['cv_mae_pct']:.2f}pp | R² {metrics['train_r2']:.4f}",
            "yield_prediction_rows": n_yp, "shap_rows": n_sh,
            "cap_ml_adjusted_rows": n_cap, **metrics}
