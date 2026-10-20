# OEE Anomaly Detection

**Implementation:** `decision_intelligence/ml/models/oee_anomaly.py`

Isolation Forest scores unusual OEE patterns. It does not diagnose a failure and its configured contamination fraction is not accuracy.

## Evaluation contract

- Fit preprocessing and the model on a historical training window.
- Score a later holdout/current window without refitting.
- Use corrected OEE inputs: availability × performance × quality.
- Explain the operational features associated with an anomaly.
- Calibrate versioned absolute severity thresholds on training data.
- Do not assign severity from each scoring batch’s relative rank.
- Preserve equipment/site/test/month identity.
- Return `not_evaluable` for empty or insufficient history.

Published records should include score, flag, severity threshold version, train window, score window, data version, and model checksum. The workflow makes no claim about a fixed anomaly count, detection rate, or business accuracy.
