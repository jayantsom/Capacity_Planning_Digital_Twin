# Silver Layer

> **Entry point**: `uv run python -m src.pipeline.silver.run_silver`
> **Files**: `src/pipeline/silver/run_silver.py`, `transforms_reference.py`, `transforms_planning.py`, `transforms_mi.py`, `utils.py`
> **Output**: 13 `slvr_` tables, 3,119,383 rows, ~135s wall time.

---

## Purpose

Silver transforms Bronze's validated-but-raw tables into **analytical-ready datasets** through joining, enrichment, feature engineering, and domain-specific calculations. The Gold layer reads exclusively from Silver — never from Bronze directly.

---

## PySpark in Local Mode

Silver uses PySpark `4.1.2` in `local[*]` mode (all available CPU cores). Data flows:

```
DuckDB (brnz_ tables)
    ↓ JDBC read via PySpark
Spark DataFrames (in-memory)
    ↓ joins, window functions, lag features
Spark DataFrames (transformed)
    ↓ collect() → pandas → DuckDB write
DuckDB (slvr_ tables)
```

> **Why PySpark here?** Silver performs multi-table joins, window-based lag computations, and conditional forward-fills across 3M+ rows. PySpark makes this scalable — the same code runs unchanged on a cluster.

**Known issue resolved**: Spark's `stack()` function requires all stacked columns to share the same type. All month columns are cast to `DOUBLE` before calling `stack()`. This is handled in `src/pipeline/silver/utils.py`.

---

## Transform Modules

| Module | Tables Written | Primary Operation |
|---|---|---|
| `transforms_reference.py` | 5 `slvr_` tables | GCM config × product × equipment master join |
| `transforms_planning.py` | 5 `slvr_` tables | Demand × hierarchy × lag features |
| `transforms_mi.py` | 3 `slvr_` tables | OEE × yield actuals × feature engineering |

---

## Module 1: `transforms_reference.py`

Builds the GCM reference dataset — the master join of all static configuration tables.

### Key join logic

```
brnz_gcm_config
  JOIN brnz_sites         ON site_code
  JOIN brnz_suppliers     ON supplier_id
  JOIN brnz_products      ON product_number
  JOIN brnz_equipment     ON equipment_id (via site_equipment_mapping)
  JOIN brnz_test_types    ON test_type
  JOIN brnz_calendar      ON month_key (cross-joined for time expansion)
```

### Key output: `slvr_gcm_reference`

One row per site × product × test_type × month × snapshot. Contains all static operational parameters needed by the capacity math engine.

Key derived columns added in Silver:

| Column | Derivation |
|---|---|
| `equip_qty_available` | Joined from `brnz_site_equipment_mapping` |
| `handling_time_sec` | Joined from `brnz_equipment` |
| `hours_per_shift_normal` | Joined from `brnz_calendar` for that month |
| `working_days_normal` | Joined from `brnz_calendar` for that month |
| `gcm_mi_join_key` | Composite key for downstream joins with actuals |

---

## Module 2: `transforms_planning.py`

Handles demand planning data: hierarchy expansion, lag features, and rolling statistics.

### Child demand calculation

This is the most critical business logic in Silver:

```python
effective_demand_qty = parent_demand_qty × child_quantity
```

For every child product in `brnz_product_hierarchy`, the child's demand is the parent's demand multiplied by the child's quantity. There is no ratio-based split — the child quantity is a fixed multiplier.

**Example**: Parent PRD-001 has demand 10,000 units. Child PRD-001-A has `child_quantity = 2`. Child effective demand = 20,000 units.

### Lag features

Computed per product × site time series using PySpark Window functions:

```python
w = Window.partitionBy("product_number", "site_code").orderBy("month_key")

df = df.withColumn("demand_lag_1",  lag("demand_qty", 1).over(w))
       .withColumn("demand_lag_3",  lag("demand_qty", 3).over(w))
       .withColumn("demand_lag_6",  lag("demand_qty", 6).over(w))
       .withColumn("demand_lag_12", lag("demand_qty", 12).over(w))
```

### Rolling statistics

```python
w3  = w.rowsBetween(-2, 0)   # 3-month trailing window
w6  = w.rowsBetween(-5, 0)   # 6-month trailing window

df = df.withColumn("demand_roll_avg_3", avg("demand_qty").over(w3))
       .withColumn("demand_roll_avg_6", avg("demand_qty").over(w6))
       .withColumn("demand_roll_std_3", stddev("demand_qty").over(w3))
```

### NPI flagging

A product × site combination is flagged as NPI if:
- Fewer than 12 months of non-zero demand history exist, **or**
- Fewer than 3 qualified test sites are mapped to the product

```python
months_of_history = count(demand_qty > 0).over(product_window)
qualified_sites   = countDistinct(site_code).over(product_window)
is_npi = (months_of_history < 12) | (qualified_sites < 3)
```

### Key output table: `slvr_demand_planning`

| Column | Source |
|---|---|
| `product_number`, `site_code`, `month_key`, `snapshot_id` | Bronze |
| `demand_qty` | Bronze |
| `effective_demand_qty` | `parent_demand_qty × child_quantity` |
| `is_npi` | Computed flag |
| `demand_lag_1..12` | Window lag |
| `demand_roll_avg_3..6` | Window rolling |
| `demand_roll_std_3` | Window rolling |
| Calendar enrichment columns | Joined from `brnz_calendar` |

---

## Module 3: `transforms_mi.py`

Manufacturing intelligence: processes OEE and yield actuals, adds time-series features.

### Yield forward-fill

Yield data has gaps — some months have no measurement. The Silver layer carries the last known value forward:

```python
w = Window.partitionBy("product_number", "site_code", "test_type") \
          .orderBy("month_key") \
          .rowsBetween(Window.unboundedPreceding, 0)

df = df.withColumn("target_yield",
       last("actual_yield", ignorenulls=True).over(w))
       .withColumn("yield_forward_filled",
       col("actual_yield").isNull().cast("integer"))
```

### Yield lag features

```python
df = df.withColumn("yield_lag_1", lag("target_yield", 1).over(w))
       .withColumn("yield_lag_3", lag("target_yield", 3).over(w))
       .withColumn("yield_roll_avg_3", avg("target_yield").over(w3))
```

### Key output: `slvr_mi_actuals`

One row per site × product × test_type × month with OEE and yield actuals, forward-filled yield, and derived lag/rolling features.

---

## Full Silver Table Inventory

| Table | Rows (approx) | Description |
|---|---|---|
| `slvr_gcm_reference` | ~766K | GCM config × all master tables joined |
| `slvr_gcm_reference_extended` | ~766K | GCM reference with calendar expansion |
| `slvr_demand_planning` | ~850K | Demand with hierarchy, lags, NPI flags |
| `slvr_demand_hierarchy` | ~400K | Explicit parent-child demand rows |
| `slvr_demand_enriched` | ~850K | Demand with all site/product attributes |
| `slvr_mi_actuals` | ~265K | OEE + yield actuals with features |
| `slvr_oee_actuals` | ~265K | OEE decomposed (avail × perf × quality) |
| `slvr_yield_actuals` | ~265K | Yield actuals with forward-fill flag |
| `slvr_site_summary` | ~22 | Site-level aggregations |
| `slvr_product_summary` | ~35 | Product-level aggregations |
| `slvr_equipment_summary` | ~181 | Site × test_type equipment summary |
| `slvr_calendar_enriched` | ~60 | Calendar with derived period flags |
| `slvr_snapshot_comparison` | ~400K | Side-by-side comparison of two snapshots |

**Total**: 3,119,383 rows across 13 tables.

---

## Key Design Decisions

**Window functions over self-joins**: Lag and rolling features are computed with PySpark Window functions rather than self-joins. This is more efficient (single pass over partitioned data) and more readable.

**Forward-fill in Silver, not Bronze**: Yield forward-fill is a business decision (carry last known value), not a validation rule. It belongs in Silver where business logic lives, not Bronze where only structural validation occurs.

**Collect to pandas before DuckDB write**: PySpark doesn't have a native DuckDB connector. After transformation, DataFrames are collected to pandas and written to DuckDB. For 3M rows this is fast enough (~135s total); for production scale, a Parquet intermediate would be used.
