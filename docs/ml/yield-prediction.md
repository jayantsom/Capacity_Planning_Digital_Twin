# Yield Prediction

**Implementation:** `decision_intelligence/ml/models/yield_prediction.py`

This workflow predicts measured production yield. Target-yield planning inputs may be covariates or comparison values, but they are not a substitute for observed yield labels.

## Evaluation and publication

- Use blocked out-of-time folds and an untouched holdout.
- Fit encoding and feature preparation only on training data.
- Preserve site, product, test/route, month, and snapshot keys.
- Compute explanations against a stable business/feature key; positional row identifiers are insufficient.
- Publish prediction, residual, evaluation status, data version, and model metadata.
- Compare holdout metrics with a naive prior-yield baseline.
- Report `not_evaluable` for insufficient or constant measured-yield history.

Capacity feedback may substitute predicted yield into the same tested capacity equations used by Gold. Joins must preserve snapshot counts and one prediction must resolve to exactly one business grain.

XGBoost and SHAP are existing implementation choices. This documentation makes no accuracy, row-count, or capacity-improvement claim.
