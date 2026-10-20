# OEE Degradation Risk

**Implementation:** `decision_intelligence/ml/models/predictive_maintenance.py`

The current label is derived from OEE behavior, not maintenance work orders or verified equipment failures. The honest product name is therefore **OEE Degradation Risk**, even if migration-era code or table names still use “predictive maintenance.”

## Required behavior

- Publish at equipment/site/test/month grain; do not repeat one resource alert for every product.
- Build labels only from information after the feature month and keep future rows out of training features.
- Split folds in temporal order.
- Run SMOTE or other resampling inside each training fold only.
- Evaluate against naive prevalence and simple threshold baselines.
- Report precision, recall, and precision-recall metrics only when evaluable.
- Return `not_evaluable` for one-class labels or insufficient history.
- Explain the synthetic threshold and avoid translating its probability into a real failure probability.

True predictive-maintenance claims require future synthetic maintenance work orders, failure modes, counters, and repair history. Those data are not part of the essential project.
