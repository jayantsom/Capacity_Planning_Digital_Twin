# Predictive Maintenance

> **File**: `src/ml/models/predictive_maintenance.py`
> **Output tables**: `gold_maintenance_risk` (265,034 rows), `gold_maintenance_alerts` (39,117 rows)
> **Run time**: ~45s

---

## What problem does this solve?

> *"Which site × test_type combinations are likely to experience OEE failure within the next 3 months — before it happens?"*

Reactive maintenance (fix after failure) causes unplanned downtime. This model flags HIGH/CRITICAL risk equipment so maintenance can be scheduled proactively.

---

## How is "failure" defined?

```python
FAILURE_THRESHOLD_OEE = 0.88
HORIZON_MONTHS        = 3
```

A row receives `failure_label = 1` if the OEE of that site × test_type drops below **0.88** within the next 3 months in the actual data.

**Why 0.88, not a lower threshold?**

| Threshold | Positive rate | Problem |
|---|---|---|
| 0.65 (generic) | 0% | No values in data fall below 0.81 — zero positive labels |
| 0.80 (data min) | ~2% | Too few positives; extreme imbalance |
| **0.88** | **13%** | Captures bottom ~13% of OEE; meaningful degradation |
| 0.92 | ~40% | Too many positives; not predictive of real failure |

0.88 sits at approximately the 15th percentile of the OEE distribution (range 0.8077–0.9767), representing genuine equipment stress.

---

## Why is class imbalance a problem here?

With 87% negative / 13% positive, a naive model that always predicts "no failure" achieves **87% accuracy** but **zero recall** — completely useless for maintenance planning. Two techniques address this:

### SMOTE (Synthetic Minority Oversampling Technique)

Generates synthetic positive examples by interpolating between existing positives in feature space:

1. For each positive example, find its $k$ nearest positive neighbours ($k=5$)
2. Randomly select one neighbour
3. Create a synthetic point along the line segment between the two

Result: class distribution balanced from 87:13 → 50:50 before XGBoost sees any data.

### `scale_pos_weight = 5`

Additional multiplicative weight on positive class in the XGBoost loss function. Acts as a second-layer correction after SMOTE.

---

## Why AUC-PR over AUC-ROC?

| Metric | What it measures | Problem with imbalanced data |
|---|---|---|
| AUC-ROC | True positive rate vs false positive rate | Inflated by large TN count; a bad model scores ~0.85+ |
| **AUC-PR** | Precision vs recall | Directly measures positive class quality; no inflation from TN |

AUC-PR of 0.9995 means the model can retrieve almost all true failures while maintaining near-perfect precision — confirming the synthetic data has strong, learnable signal.

---

## What features are used?

| Feature group | Columns |
|---|---|
| OEE history | `avg_oee_lag1..6`, `avg_oee_roll3_mean`, `_roll6_mean`, `_roll3_std`, `_roll6_std` |
| OEE trend | `oee_trend_3m` = `avg_oee − avg_oee.shift(3)` (negative = degrading) |
| Yield signals | `avg_yield_lag1..3`, `avg_yield_roll3_mean` |
| Demand load | `demand_lag1..3`, `demand_roll3_mean` |
| Time | `month_of_year`, `year` |
| Encoded categoricals | `site_id_enc`, `product_id_enc`, `test_type_id_enc` |

**Excluded from features**: raw `avg_oee`, `avg_yield`, `demand` (to prevent data leakage — only lagged values are available at prediction time).

---

## Training process

| Step | Detail |
|---|---|
| Label generation | Scan forward 3 months per site × test_type; label=1 if OEE < 0.88 |
| Feature engineering | Lag + rolling OEE, yield, demand; OEE trend; encode categoricals |
| SMOTE | `k_neighbors = min(5, positive_count - 1)` (safe for small classes) |
| CV | 5-fold `StratifiedKFold`; metric = AUC-PR |
| Final model | Retrain on full SMOTE-resampled data |
| Scoring | `predict_proba()[:, 1]` → `failure_prob` for all rows |
| Risk tiers | Cut on [0, 0.20, 0.40, 0.70, 1.0] → LOW/MEDIUM/HIGH/CRITICAL |

---

## XGBoost hyperparameters

| Parameter | Value |
|---|---|
| `n_estimators` | 300 |
| `learning_rate` | 0.05 |
| `max_depth` | 5 |
| `subsample` | 0.8 |
| `colsample_bytree` | 0.8 |
| `scale_pos_weight` | 5 |
| `eval_metric` | `aucpr` |

Shallower trees (depth 5) than yield model — maintenance signal is simpler (OEE trend dominates).

---

## Results

| Metric | Value |
|---|---|
| Positive rate | 13.0% |
| CV AUC-PR | **0.9995** |
| Train ROC-AUC | **0.9983** |
| Risk rows | 265,034 |
| HIGH/CRITICAL alerts | 39,117 (~15%) |

---

## Output table schemas

### `gold_maintenance_risk`

| Column | Type | Description |
|---|---|---|
| `site_id`, `test_type_id` | VARCHAR | Equipment identifier |
| `month` | INTEGER | yyyymm |
| `avg_oee` | DOUBLE | OEE value |
| `failure_label` | INTEGER | Actual label (0/1) |
| `failure_prob` | DOUBLE | Predicted probability |
| `risk_tier` | VARCHAR | LOW/MEDIUM/HIGH/CRITICAL |

### `gold_maintenance_alerts`

Same schema as `gold_maintenance_risk`, filtered to `risk_tier IN ('HIGH', 'CRITICAL')`, plus:

| Column | Type | Description |
|---|---|---|
| `alert_generated_at` | VARCHAR | UTC timestamp of alert generation |
