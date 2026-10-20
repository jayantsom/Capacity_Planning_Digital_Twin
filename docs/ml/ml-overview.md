# Decision Intelligence

`decision_intelligence/` owns five workflows, their atomic publication, and five
tabbed dashboards. The project does not add MLflow or a separate feature-store platform.

| Workflow | Purpose | Honest description |
|---|---|---|
| Demand forecasting | Forecast telecom demand by declared series | Prophet/XGBoost/LightGBM with time-aware features |
| Yield prediction | Predict measured production yield | XGBoost with keyed explanations and capacity feedback |
| OEE degradation risk | Score near-term OEE degradation | Classification proxy, not equipment-failure prediction |
| OEE anomaly | Flag unusual OEE patterns | Isolation Forest; contamination is a configured rate, not accuracy |
| CapEx | Estimate equipment needs under uncertainty | Monte Carlo simulation, not mathematical optimization |

## Evaluation contract

- Split by unique months: train, validation, then untouched holdout.
- Fit preprocessing, encoders, resampling, and model selection only inside training folds.
- Compute lag and rolling features inside each series and strictly behind the target.
- Enable Prophet yearly seasonality only when a series spans at least two complete years.
- Collapse qualified-resource fan-out before creating product/site/test/month ML rows.
- Preserve business keys and snapshots through sorting, prediction, explanation, and publication.
- Compare every reported metric with a declared naive baseline.
- Return `not_evaluable` with a reason for empty data, insufficient history, constant targets, one-class labels, or zero-only targets.
- Mark rows as train, validation, holdout, or future inference.
- Record train/holdout windows, seed, data/config/code versions, feature schema, library versions, and model checksum.

Serialized models are trusted promoted artifacts only. APIs cannot supply model paths.

```powershell
# Run all five workflows through the project script.
uv run capacity-ml
```

All five workflows have been exercised together against the bounded generated dataset and
published through the atomic ML candidate gate. Reported scores remain run-specific; this
documentation does not claim fixed production-quality performance.
