"""
Priority 1 — Demand Forecasting
================================
Ensemble: Prophet (trend/seasonality) + XGBoost + LightGBM (lag features).
NPI products use Croston's Intermittent Demand method.

Internal column names (after load_feature_store normalisation):
  product_id, site_id, platform_id, family_id, test_type_id,
  month (INTEGER yyyymm), demand, avg_yield, avg_oee

Output tables:
  gold_demand_forecast       — 18-month horizon per product×site
  gold_forecast_accuracy_ml  — backtested accuracy vs actuals (last 6 months)
"""

import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd
from prophet import Prophet
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBRegressor

from src.utils.logger import logger as log
from src.utils.ml_utils import (
    add_lag_features,
    add_rolling_features,
    encode_categoricals,
    get_conn,
    load_feature_store,
    mape,
    rmse,
    save_model,
    smape,
    upsert_table,
)

warnings.filterwarnings("ignore")

# ── Config ───────────────────────────────────────────────────────────────────
FORECAST_HORIZON  = 18
BACKTEST_MONTHS   = 6
MIN_HISTORY       = 12
NPI_MAX_HISTORY   = 6
ENSEMBLE_WEIGHTS  = {"prophet": 0.35, "xgb": 0.35, "lgbm": 0.30}

CAT_COLS  = ["site_id", "product_id", "platform_id", "family_id", "test_type_id"]
LAG_COLS  = [1, 2, 3, 6, 12]
ROLL_COLS = [3, 6, 12]

# month_key is INTEGER yyyymm — convert to ordinal for tree models
def _month_to_ordinal(m: int) -> int:
    y, mo = divmod(m, 100)
    return y * 12 + mo


# ── Croston ──────────────────────────────────────────────────────────────────

def croston_forecast(series: pd.Series, horizon: int, alpha: float = 0.1) -> np.ndarray:
    y = series.values.astype(float)
    non_zero = y[y > 0]
    if len(non_zero) == 0:
        return np.zeros(horizon)
    a_level = non_zero[0]
    q_level = 1.0
    for i in range(1, len(non_zero)):
        a_level = alpha * non_zero[i] + (1 - alpha) * a_level
        inter = np.where(y > 0)[0]
        if len(inter) > 1:
            q_level = alpha * np.diff(inter).mean() + (1 - alpha) * q_level
    return np.full(horizon, a_level / max(q_level, 1.0))


# ── Feature engineering ──────────────────────────────────────────────────────

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("month").copy()
    df["month_ordinal"] = df["month"].apply(_month_to_ordinal)
    df["month_of_year"] = df["month"] % 100
    df["year"]          = df["month"] // 100
    df["quarter"]       = ((df["month_of_year"] - 1) // 3) + 1

    df = add_lag_features(df, "demand", LAG_COLS)
    df = add_rolling_features(df, "demand", ROLL_COLS)

    for col in ["avg_yield", "avg_oee"]:
        if col in df.columns:
            df = add_lag_features(df, col, [1, 3])

    return df


def _feat_cols(df: pd.DataFrame) -> list[str]:
    exclude = {"month", "demand", "snapshot_id", "feat_pk",
               "product_status", "region", "supplier_name"}
    return [
        c for c in df.columns
        if c not in exclude
        and df[c].dtype in [np.float64, np.int64, np.int32, float, int]
    ]


# ── Prophet ──────────────────────────────────────────────────────────────────

def _month_key_to_timestamp(mk: int) -> pd.Timestamp:
    y, m = divmod(mk, 100)
    return pd.Timestamp(year=y, month=m, day=1)


def fit_prophet(series: pd.Series, future_months: int) -> np.ndarray:
    ds = [_month_key_to_timestamp(mk) for mk in series.index]
    prophet_df = pd.DataFrame({"ds": ds, "y": series.values})
    prophet_df = prophet_df[prophet_df["y"] > 0]
    if len(prophet_df) < MIN_HISTORY:
        return np.full(future_months, float(series.mean()))
    m = Prophet(
        changepoint_prior_scale=0.05,
        seasonality_mode="multiplicative",
        yearly_seasonality=True,
        weekly_seasonality=False,
        daily_seasonality=False,
    )
    m.fit(prophet_df, iter=300)
    future = m.make_future_dataframe(periods=future_months, freq="MS")
    fc = m.predict(future)
    return fc["yhat"].values[-future_months:].clip(0)


# ── Tree models ──────────────────────────────────────────────────────────────

XGB_PARAMS = dict(n_estimators=300, learning_rate=0.05, max_depth=6,
                  subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
                  reg_alpha=0.1, reg_lambda=1.0, random_state=42, n_jobs=-1)

LGB_PARAMS = dict(n_estimators=300, learning_rate=0.05, num_leaves=63,
                  max_depth=6, subsample=0.8, colsample_bytree=0.8,
                  min_child_samples=5, reg_alpha=0.1, reg_lambda=1.0,
                  random_state=42, n_jobs=-1, verbose=-1)


def fit_tree_models(train_df: pd.DataFrame):
    feat_cols = _feat_cols(train_df)
    X = train_df[feat_cols].fillna(0)
    y = train_df["demand"].clip(0)
    xgb  = XGBRegressor(**XGB_PARAMS);  xgb.fit(X, y)
    lgbm = lgb.LGBMRegressor(**LGB_PARAMS); lgbm.fit(X, y)
    return xgb, lgbm, feat_cols


# ── Future month keys ────────────────────────────────────────────────────────

def _future_month_keys(last_mk: int, n: int) -> list[int]:
    y, m = divmod(last_mk, 100)
    keys = []
    for _ in range(n):
        m += 1
        if m > 12:
            m = 1; y += 1
        keys.append(y * 100 + m)
    return keys


# ── Forecast one series ──────────────────────────────────────────────────────

def forecast_one_series(grp_df, product_id, site_id, xgb_model, lgbm_model,
                        feat_cols, is_npi, horizon) -> list[dict]:
    series = grp_df.set_index("month")["demand"].sort_index()
    last_mk = series.index[-1]
    future_mks = _future_month_keys(last_mk, horizon)

    if is_npi or len(series) < NPI_MAX_HISTORY:
        fc_vals = croston_forecast(series, horizon)
        method  = "croston"
    else:
        prophet_fc = fit_prophet(series, horizon)

        last_row = grp_df.sort_values("month").iloc[-1:].copy()
        future_rows = pd.concat([last_row] * horizon, ignore_index=True)
        future_rows["month"]        = future_mks
        future_rows["month_ordinal"]= [_month_to_ordinal(mk) for mk in future_mks]
        future_rows["month_of_year"]= [mk % 100 for mk in future_mks]
        future_rows["year"]         = [mk // 100 for mk in future_mks]
        future_rows["quarter"]      = [((mk % 100 - 1) // 3) + 1 for mk in future_mks]

        available_feat_cols = [c for c in feat_cols if c in future_rows.columns]
        X_fut = future_rows[available_feat_cols].fillna(0)

        xgb_fc  = xgb_model.predict(X_fut).clip(0)
        lgbm_fc = lgbm_model.predict(X_fut).clip(0)

        fc_vals = (ENSEMBLE_WEIGHTS["prophet"] * prophet_fc
                   + ENSEMBLE_WEIGHTS["xgb"]    * xgb_fc
                   + ENSEMBLE_WEIGHTS["lgbm"]   * lgbm_fc)
        method = "ensemble"

    return [
        {"product_id": product_id, "site_id": site_id,
         "forecast_month_key": mk, "forecast_horizon_months": i + 1,
         "demand_forecast": round(float(v), 2), "forecast_method": method}
        for i, (mk, v) in enumerate(zip(future_mks, fc_vals))
    ]


# ── Backtest ─────────────────────────────────────────────────────────────────

def backtest_accuracy(df, xgb_model, lgbm_model, feat_cols) -> pd.DataFrame:
    rows = []
    for (product_id, site_id), grp in df.groupby(["product_id", "site_id"]):
        grp = grp.sort_values("month")
        if len(grp) <= BACKTEST_MONTHS:
            continue
        train = grp.iloc[:-BACKTEST_MONTHS]
        test  = grp.iloc[-BACKTEST_MONTHS:]

        series_train = train.set_index("month")["demand"]
        prophet_fc   = fit_prophet(series_train, BACKTEST_MONTHS)

        available = [c for c in feat_cols if c in test.columns]
        xgb_fc    = xgb_model.predict(test[available].fillna(0)).clip(0)
        lgbm_fc   = lgbm_model.predict(test[available].fillna(0)).clip(0)

        ens    = (ENSEMBLE_WEIGHTS["prophet"] * prophet_fc
                  + ENSEMBLE_WEIGHTS["xgb"]   * xgb_fc
                  + ENSEMBLE_WEIGHTS["lgbm"]  * lgbm_fc)
        y_true = test["demand"].values

        rows.append({"product_id": product_id, "site_id": site_id,
                     "backtest_months": BACKTEST_MONTHS,
                     "mape_pct":  round(mape(y_true, ens), 2),
                     "smape_pct": round(smape(y_true, ens), 2),
                     "rmse":      round(rmse(y_true, ens), 2),
                     "mae":       round(float(mean_absolute_error(y_true, ens)), 2)})
    return pd.DataFrame(rows)


# ── Entry point ──────────────────────────────────────────────────────────────

def run_demand_forecast() -> dict:
    conn = get_conn()
    log.info("Loading feature store...")
    fs = load_feature_store(conn)

    history_len = fs.groupby(["product_id", "site_id"])["month"].nunique()
    npi_keys    = set(history_len[history_len < MIN_HISTORY].index.tolist())
    log.info(f"  NPI product-site combos (Croston): {len(npi_keys)}")

    log.info("Engineering features...")
    fs_feat = build_features(fs)
    fs_feat = encode_categoricals(fs_feat, CAT_COLS)

    log.info("Training XGBoost + LightGBM...")
    train_df = (
        fs_feat.groupby(["product_id", "site_id"], group_keys=False)
        .apply(lambda g: g.sort_values("month").iloc[:-BACKTEST_MONTHS]
               if len(g) > BACKTEST_MONTHS else g)
    )
    xgb_model, lgbm_model, feat_cols = fit_tree_models(train_df)
    save_model(xgb_model,  "demand_xgb",  {"features": feat_cols})
    save_model(lgbm_model, "demand_lgbm", {"features": feat_cols})

    log.info("Running backtest accuracy...")
    accuracy_df = backtest_accuracy(fs_feat, xgb_model, lgbm_model, feat_cols)
    median_mape = accuracy_df["mape_pct"].median() if len(accuracy_df) else float("nan")
    log.info(f"  Median MAPE: {median_mape:.1f}%")

    log.info("Retraining on full data...")
    xgb_full, lgbm_full, feat_cols_full = fit_tree_models(fs_feat)

    log.info(f"Generating {FORECAST_HORIZON}-month forecasts...")
    all_records = []
    for (product_id, site_id), grp in fs_feat.groupby(["product_id", "site_id"]):
        is_npi = (product_id, site_id) in npi_keys
        all_records.extend(
            forecast_one_series(grp, product_id, site_id,
                                xgb_full, lgbm_full, feat_cols_full,
                                is_npi, FORECAST_HORIZON)
        )

    forecast_df = pd.DataFrame(all_records)

    n_fc  = upsert_table(conn, forecast_df, "gold_demand_forecast")
    n_acc = upsert_table(conn, accuracy_df, "gold_forecast_accuracy_ml")
    conn.close()

    log.info(f"  Wrote gold_demand_forecast: {n_fc:,} rows")
    log.info(f"  Wrote gold_forecast_accuracy_ml: {n_acc:,} rows")

    return {"summary": f"{n_fc:,} forecast rows | median MAPE {median_mape:.1f}%",
            "forecast_rows": n_fc, "accuracy_rows": n_acc,
            "median_mape_pct": round(median_mape, 2)}
