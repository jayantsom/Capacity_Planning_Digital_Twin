# Demand Forecasting

**Implementation:** `decision_intelligence/ml/models/demand_forecast.py`

The workflow forecasts demand at one declared product/site series grain. It trains only on historical actuals; future planning rows are not training targets.

## Requirements

- Aggregate duplicate source rows before feature creation.
- Compute lag and rolling features within each series and shift them behind the target month.
- Split train, validation, and holdout by unique months.
- Keep the final holdout outside feature fitting and model selection.
- Compare Prophet/XGBoost/LightGBM outputs with a declared naive seasonal or last-value baseline.
- Generate multi-step tree forecasts recursively or directly with horizon-correct features.
- Reject duplicate series/month output keys.
- Return `not_evaluable` when history is insufficient or the target cannot support a metric.

Prophet, XGBoost, and LightGBM remain the existing candidate models. The implementation must not describe copied last-known lag rows as a fully recursive forecast.

Outputs must identify series keys, forecast month, horizon, method, data version, training window, holdout window, and evaluation status. No row count, runtime, MAPE, or quality level is guaranteed until a promoted telecom run is evaluated.
