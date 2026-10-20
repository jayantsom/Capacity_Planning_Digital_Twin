"""
Priority 1 — Demand Forecasting
================================
Ensemble: Prophet (trend/seasonality) + XGBoost + LightGBM (lag features).
Series with repeated zero-demand periods use Croston's intermittent-demand method.

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
from xgboost import XGBRegressor

from capacity_twin_core.logging import logger as log
from decision_intelligence.ml_support import (
    add_lag_features,
    add_rolling_features,
    get_conn,
    load_feature_store,
    mape,
    metric_result,
    rmse,
    save_model,
    smape,
    temporal_split,
    upsert_table,
)

warnings.filterwarnings("ignore")

# ── Config ───────────────────────────────────────────────────────────────────
FORECAST_HORIZON = 18
BACKTEST_MONTHS = 6
MIN_HISTORY = 12
ENSEMBLE_WEIGHTS = {"prophet": 0.35, "xgb": 0.35, "lgbm": 0.30}

LAG_COLS = [1, 2, 3, 6, 12]
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


def is_intermittent_demand(
    series: pd.Series,
    *,
    minimum_zero_share: float = 0.25,
) -> bool:
    """Use Croston only when a series contains repeated zero-demand periods."""
    values = series.fillna(0).clip(lower=0)
    return len(values) >= 6 and float((values == 0).mean()) >= minimum_zero_share


# ── Feature engineering ──────────────────────────────────────────────────────


def prepare_demand_series(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse test/snapshot fan-out to one historical product-site-month row."""
    actual = df.copy()
    if "is_actual" in actual:
        actual = actual[actual["is_actual"].fillna(0).astype(int) == 1]
    elif "data_type" in actual:
        actual = actual[actual["data_type"].astype(str).str.upper() == "ACTUAL"]
    if actual.empty:
        raise ValueError("No historical actual demand rows are available")

    keys = ["product_id", "site_id", "month"]
    # Demand is repeated for each required test and snapshot, so summing is wrong.
    varying = actual.groupby(keys)["demand"].nunique(dropna=True)
    if (varying > 1).any():
        raise ValueError("Conflicting demand values at product/site/month grain")
    metadata = [
        col for col in ["platform_id", "family_id", "product_status"] if col in actual.columns
    ]
    aggregations = {"demand": "first", **{col: "first" for col in metadata}}
    return (
        actual.sort_values(keys + (["snapshot_id"] if "snapshot_id" in actual else []))
        .groupby(keys, as_index=False)
        .agg(aggregations)
        .sort_values(keys)
        .reset_index(drop=True)
    )


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build leakage-safe features independently inside each demand series."""
    groups = ["product_id", "site_id"]
    df = df.sort_values(groups + ["month"]).copy()
    df["month_ordinal"] = df["month"].apply(_month_to_ordinal)
    df["month_of_year"] = df["month"] % 100
    df["year"] = df["month"] // 100
    df["quarter"] = ((df["month_of_year"] - 1) // 3) + 1

    df = add_lag_features(df, "demand", LAG_COLS, groups)
    df = add_rolling_features(df, "demand", ROLL_COLS, groups)

    for col in ["avg_yield", "avg_oee"]:
        if col in df.columns:
            df = add_lag_features(df, col, [1, 3], groups)

    return df


def _feat_cols(df: pd.DataFrame) -> list[str]:
    exclude = {
        "month",
        "demand",
        "snapshot_id",
        "feat_pk",
        "feature_row_id",
        "product_id",
        "site_id",
        "platform_id",
        "family_id",
        "test_type_id",
        "product_status",
        "region",
        "supplier_name",
        "is_actual",
        "data_type",
    }
    return [
        c
        for c in df.columns
        if c not in exclude and df[c].dtype in [np.float64, np.int64, np.int32, float, int]
    ]


# ── Prophet ──────────────────────────────────────────────────────────────────


def _month_key_to_timestamp(mk: int) -> pd.Timestamp:
    y, m = divmod(mk, 100)
    return pd.Timestamp(year=y, month=m, day=1)


def supports_yearly_seasonality(months: pd.Series | pd.Index) -> bool:
    """Require at least two complete calendar-year spans before fitting seasonality."""
    timestamps = pd.DatetimeIndex(
        [_month_key_to_timestamp(int(month)) for month in months]
    ).sort_values()
    if len(timestamps.unique()) < 25:
        return False
    return bool(timestamps.max() - timestamps.min() >= pd.Timedelta(days=730))


def fit_prophet(series: pd.Series, future_months: int) -> np.ndarray:
    ds = [_month_key_to_timestamp(mk) for mk in series.index]
    prophet_df = pd.DataFrame({"ds": ds, "y": series.values})
    prophet_df = prophet_df[prophet_df["y"] > 0]
    if len(prophet_df) < MIN_HISTORY:
        return np.full(future_months, float(series.mean()))
    yearly_seasonality = supports_yearly_seasonality(
        prophet_df["ds"].dt.year * 100 + prophet_df["ds"].dt.month
    )
    m = Prophet(
        changepoint_prior_scale=0.05,
        seasonality_mode="multiplicative",
        yearly_seasonality=yearly_seasonality,
        weekly_seasonality=False,
        daily_seasonality=False,
    )
    m.fit(prophet_df, iter=300)
    future = m.make_future_dataframe(periods=future_months, freq="MS")
    fc = m.predict(future)
    return fc["yhat"].values[-future_months:].clip(0)


# ── Tree models ──────────────────────────────────────────────────────────────

XGB_PARAMS = {
    "n_estimators": 300,
    "learning_rate": 0.05,
    "max_depth": 6,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 3,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_jobs": -1,
}

LGB_PARAMS = {
    "n_estimators": 300,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "max_depth": 6,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_samples": 5,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}


def fit_tree_models(train_df: pd.DataFrame):
    feat_cols = _feat_cols(train_df)
    X = train_df[feat_cols].fillna(0)
    y = train_df["demand"].clip(0)
    xgb = XGBRegressor(**XGB_PARAMS)
    xgb.fit(X, y)
    lgbm = lgb.LGBMRegressor(**LGB_PARAMS)
    lgbm.fit(X, y)
    return xgb, lgbm, feat_cols


# ── Future month keys ────────────────────────────────────────────────────────


def _future_month_keys(last_mk: int, n: int) -> list[int]:
    y, m = divmod(last_mk, 100)
    keys = []
    for _ in range(n):
        m += 1
        if m > 12:
            m = 1
            y += 1
        keys.append(y * 100 + m)
    return keys


# ── Forecast one series ──────────────────────────────────────────────────────


def _recursive_tree_forecast(
    history: pd.DataFrame,
    future_mks: list[int],
    model,
    feat_cols: list[str],
) -> np.ndarray:
    """Recompute horizon-correct lags after every predicted month."""
    working = history.copy()
    predictions: list[float] = []
    for month in future_mks:
        next_row = working.iloc[-1:].copy()
        next_row["month"] = month
        next_row["demand"] = np.nan
        candidate = pd.concat([working, next_row], ignore_index=True)
        featured = build_features(candidate)
        row = featured.iloc[-1:]
        available = [col for col in feat_cols if col in row.columns]
        prediction = float(model.predict(row[available].fillna(0))[0])
        next_row["demand"] = max(prediction, 0.0)
        working = pd.concat([working, next_row], ignore_index=True)
        predictions.append(max(prediction, 0.0))
    return np.asarray(predictions)


def forecast_one_series(
    grp_df, product_id, site_id, xgb_model, lgbm_model, feat_cols, horizon
) -> list[dict]:
    series = grp_df.set_index("month")["demand"].sort_index()
    last_mk = series.index[-1]
    future_mks = _future_month_keys(last_mk, horizon)

    if is_intermittent_demand(series):
        fc_vals = croston_forecast(series, horizon)
        method = "croston"
    else:
        prophet_fc = fit_prophet(series, horizon)

        raw_history = grp_df[
            [col for col in grp_df.columns if "_lag" not in col and "_roll" not in col]
        ].copy()
        xgb_fc = _recursive_tree_forecast(raw_history, future_mks, xgb_model, feat_cols)
        lgbm_fc = _recursive_tree_forecast(raw_history, future_mks, lgbm_model, feat_cols)

        fc_vals = (
            ENSEMBLE_WEIGHTS["prophet"] * prophet_fc
            + ENSEMBLE_WEIGHTS["xgb"] * xgb_fc
            + ENSEMBLE_WEIGHTS["lgbm"] * lgbm_fc
        )
        method = "ensemble"

    return [
        {
            "product_id": product_id,
            "site_id": site_id,
            "forecast_month_key": mk,
            "forecast_horizon_months": i + 1,
            "demand_forecast": round(float(v), 2),
            "forecast_method": method,
        }
        for i, (mk, v) in enumerate(zip(future_mks, fc_vals))
    ]


# ── Backtest ─────────────────────────────────────────────────────────────────


def backtest_accuracy(df, xgb_model, lgbm_model, feat_cols) -> pd.DataFrame:
    rows = []
    for (product_id, site_id), grp in df.groupby(["product_id", "site_id"]):
        grp = grp.sort_values("month")
        if len(grp) <= BACKTEST_MONTHS:
            continue
        train = grp.iloc[:-BACKTEST_MONTHS].copy()
        test = grp.iloc[-BACKTEST_MONTHS:].copy()

        series_train = train.set_index("month")["demand"]
        prophet_fc = fit_prophet(series_train, BACKTEST_MONTHS)

        future_mks = test["month"].astype(int).tolist()
        raw_train = train[
            [col for col in train.columns if "_lag" not in col and "_roll" not in col]
        ]
        xgb_fc = _recursive_tree_forecast(raw_train, future_mks, xgb_model, feat_cols)
        lgbm_fc = _recursive_tree_forecast(raw_train, future_mks, lgbm_model, feat_cols)

        ens = (
            ENSEMBLE_WEIGHTS["prophet"] * prophet_fc
            + ENSEMBLE_WEIGHTS["xgb"] * xgb_fc
            + ENSEMBLE_WEIGHTS["lgbm"] * lgbm_fc
        )
        y_true = test["demand"].values

        naive = np.repeat(float(train["demand"].iloc[-1]), len(test))
        evaluation = metric_result(y_true, ens, naive_pred=naive)
        mape_value = mape(y_true, ens)
        rows.append(
            {
                "product_id": product_id,
                "site_id": site_id,
                "backtest_months": BACKTEST_MONTHS,
                "mape_pct": round(mape_value, 2) if np.isfinite(mape_value) else None,
                "smape_pct": round(smape(y_true, ens), 2),
                "rmse": round(rmse(y_true, ens), 2),
                "mae": round(float(mean_absolute_error(y_true, ens)), 2),
                "naive_mae": round(float(evaluation["naive_mae"]), 2),
                "beats_naive_mae": evaluation["beats_naive_mae"],
            }
        )
    return pd.DataFrame(rows)


# ── Entry point ──────────────────────────────────────────────────────────────


def run_demand_forecast() -> dict:
    conn = get_conn()
    log.info("Loading feature store...")
    fs = prepare_demand_series(load_feature_store(conn))

    history_len = fs.groupby(["product_id", "site_id"])["month"].nunique()
    npi_keys = set(history_len[history_len < MIN_HISTORY].index.tolist())
    log.info(f"  Short-history product-site combos: {len(npi_keys)}")

    log.info("Engineering features...")
    fs_feat = build_features(fs)

    log.info("Training XGBoost + LightGBM...")
    train_df, validation_df, holdout_df = temporal_split(
        fs_feat,
        holdout_months=BACKTEST_MONTHS,
        validation_months=3,
        minimum_train_months=MIN_HISTORY,
    )
    xgb_model, lgbm_model, feat_cols = fit_tree_models(train_df)
    log.info("Running backtest accuracy...")
    accuracy_df = backtest_accuracy(fs_feat, xgb_model, lgbm_model, feat_cols)
    if accuracy_df.empty:
        raise ValueError("Demand forecast is not evaluable: no series has a holdout window")
    valid_mape = accuracy_df["mape_pct"].dropna()
    median_mape = float(valid_mape.median()) if not valid_mape.empty else None
    if median_mape is None:
        log.info("  Median MAPE: not evaluable because holdout actuals are zero-only")
    else:
        log.info(f"  Median MAPE: {median_mape:.1f}%")

    log.info("Retraining production models on all evaluated history...")
    production_train = fs_feat.copy()
    xgb_full, lgbm_full, feat_cols_full = fit_tree_models(production_train)
    model_metadata = {
        "feature_schema": feat_cols_full,
        "train_window": [
            int(production_train["month"].min()),
            int(production_train["month"].max()),
        ],
        "evaluation_train_window": [
            int(train_df["month"].min()),
            int(train_df["month"].max()),
        ],
        "validation_window": [
            int(validation_df["month"].min()),
            int(validation_df["month"].max()),
        ],
        "holdout_window": [
            int(holdout_df["month"].min()),
            int(holdout_df["month"].max()),
        ],
        "median_mape_pct": median_mape,
    }
    save_model(xgb_full, "demand_xgb", model_metadata)
    save_model(lgbm_full, "demand_lgbm", model_metadata)

    log.info(f"Generating {FORECAST_HORIZON}-month forecasts...")
    all_records = []
    for (product_id, site_id), grp in fs_feat.groupby(["product_id", "site_id"]):
        all_records.extend(
            forecast_one_series(
                grp,
                product_id,
                site_id,
                xgb_full,
                lgbm_full,
                feat_cols_full,
                FORECAST_HORIZON,
            )
        )

    forecast_df = pd.DataFrame(all_records)
    key_cols = ["product_id", "site_id", "forecast_month_key"]
    if forecast_df.duplicated(key_cols).any():
        raise ValueError("Demand forecast contains duplicate series-month keys")

    n_fc = upsert_table(conn, forecast_df, "gold_demand_forecast")
    n_acc = upsert_table(conn, accuracy_df, "gold_forecast_accuracy_ml")
    conn.close()

    log.info(f"  Wrote gold_demand_forecast: {n_fc:,} rows")
    log.info(f"  Wrote gold_forecast_accuracy_ml: {n_acc:,} rows")

    metric_summary = (
        f"median MAPE {median_mape:.1f}%"
        if median_mape is not None
        else "MAPE not evaluable (zero-only holdout)"
    )
    return {
        "summary": f"{n_fc:,} forecast rows | {metric_summary}",
        "forecast_rows": n_fc,
        "accuracy_rows": n_acc,
        "median_mape_pct": round(median_mape, 2) if median_mape is not None else None,
    }
