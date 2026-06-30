# OEE Anomaly Detection

> **File**: `src/ml/models/oee_anomaly.py`
> **Output tables**: `gold_oee_anomalies` (265,034 rows), `gold_oee_anomaly_summary` (22 rows)
> **Run time**: ~10s

---

## What problem does this solve?

> *"Which site × test_type × month combinations show statistically unusual OEE behaviour — regardless of whether a fixed threshold is crossed?"*

Predictive Maintenance (Priority 3) requires a labelled failure definition (OEE < 0.88). Anomaly detection catches everything else — sudden drops, unusual volatility, drift patterns — without needing a predefined threshold or any labels at all.

---

## Why unsupervised, and why Isolation Forest specifically?

| Requirement | Why Isolation Forest fits |
|---|---|
| No labels available | Pure unsupervised method — no `failure_label` needed |
| Multiple anomaly types | Detects point anomalies, not just threshold crossings |
| Scales to 265K rows | $O(n \log n)$ training, fast inference |
| No distributional assumptions | Works on raw feature space, no Gaussian assumption like older methods |

**How it works**: builds an ensemble of random trees. Each tree isolates a point by randomly selecting a feature and a random split value. Anomalous points — being far from the bulk of the data — require **fewer splits** to isolate than normal points.

$$\text{anomaly score} = 2^{-\frac{E[h(x)]}{c(n)}}$$

Where $E[h(x)]$ is the average path length to isolate point $x$ across all trees, and $c(n)$ is a normalisation constant. Shorter average path → higher anomaly score.

---

## What does `contamination = 0.05` control?

It sets the expected fraction of anomalies in the training data, which determines the decision threshold on the anomaly score. **5% of all rows will be flagged**, regardless of dataset size — this is a design choice, not a data-driven discovery.

**Verification**: 13,252 / 265,034 = exactly 5.0% — confirms the parameter is working as intended.

---

## What features feed the model?

| Feature group | Columns |
|---|---|
| OEE history | `avg_oee_lag1..3`, `_roll3_mean`, `_roll6_mean`, `_roll3_std`, `_roll6_std` |
| OEE volatility | `avg_oee_vol_3m` = rolling 3-month standard deviation |
| OEE deviation | `oee_deviation_from_site` = `avg_oee − site_mean_oee` |
| Yield signals | `avg_yield_lag1..3`, rolling stats |
| Demand signals | `demand_lag1..3`, rolling stats |
| Time | `month_of_year`, `year` |

**No categorical encoding needed** — Isolation Forest splits are purely on numeric thresholds, so `site_id`/`test_type_id` are excluded from the feature matrix (they're retained only as row identifiers in the output).

---

## Why StandardScaler before training?

Isolation Forest splits are scale-sensitive when features have very different ranges (e.g. `demand_qty` in thousands vs `avg_oee` in [0,1]). `StandardScaler` normalises all features to zero mean, unit variance, ensuring no single feature dominates the random splits purely due to its scale.

```python
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)
iso = IsolationForest(n_estimators=200, contamination=0.05, random_state=42)
iso.fit(X_scaled)
```

---

## How are severity tiers assigned?

Anomaly score is converted to a percentile rank, then cut into 4 tiers:

| Percentile of score | Tier |
|---|---|
| Bottom 2% | CRITICAL |
| 2%–5% | HIGH |
| 5%–10% | MEDIUM |
| Top 90% | NORMAL |

This is a finer-grained breakdown than the binary `anomaly_flag` — useful for prioritising investigation order.

---

## Training process

| Step | Detail |
|---|---|
| Filter | Rows where `avg_oee` is non-null → 265,034 rows |
| Features | OEE/yield/demand lags, rolling stats, volatility, site deviation |
| Scale | `StandardScaler.fit_transform()` |
| Train | `IsolationForest(n_estimators=200, contamination=0.05)` |
| Score | `score_samples()` → continuous anomaly score; `predict()` → binary flag |
| Severity | Percentile rank → CRITICAL/HIGH/MEDIUM/NORMAL |
| Summary | Group by site → anomaly rate, mean/min OEE |

---

## Isolation Forest hyperparameters

| Parameter | Value | Rationale |
|---|---|---|
| `n_estimators` | 200 | Standard ensemble size; stable scores beyond this |
| `contamination` | 0.05 | 5% expected anomaly rate (design choice) |
| `max_samples` | `auto` (= min(256, n)) | Default; sufficient for stable isolation |

---

## Results

| Metric | Value |
|---|---|
| Rows scored | 265,034 |
| Anomalies flagged | 13,252 (exactly 5.0%) |
| Site summary rows | 22 (one per site) |

---

## Output table schemas

### `gold_oee_anomalies`

| Column | Type | Description |
|---|---|---|
| `site_id`, `test_type_id` | VARCHAR | Equipment identifier |
| `month` | INTEGER | yyyymm |
| `avg_oee` | DOUBLE | OEE value |
| `anomaly_score` | DOUBLE | Continuous score (higher = more normal) |
| `anomaly_flag` | INTEGER | 1 = anomaly, 0 = normal |
| `anomaly_severity` | VARCHAR | CRITICAL/HIGH/MEDIUM/NORMAL |

### `gold_oee_anomaly_summary`

| Column | Type | Description |
|---|---|---|
| `site_id` | VARCHAR | Site code |
| `total_records` | INTEGER | Rows for this site |
| `anomaly_count` | INTEGER | Flagged rows |
| `anomaly_rate_pct` | DOUBLE | `anomaly_count / total_records × 100` |
| `mean_oee`, `min_oee` | DOUBLE | Site-level OEE stats |
