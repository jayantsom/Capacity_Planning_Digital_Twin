# Validation & Testing

---

## Layer verification queries

Run these in the Data Explorer SQL editor (`http://localhost:8001/explorer/`) against `duckdb_analytics`.

### Bronze
```sql
SELECT table_name,
       COUNT(*) FILTER (WHERE table_name LIKE 'brnz_%') AS bronze_tables
FROM information_schema.tables WHERE table_schema = 'main';
-- Expected: 12 bronze tables
```

### Silver
```sql
SELECT 'slvr_demand_planning' AS t, COUNT(*) AS n FROM slvr_demand_planning
UNION ALL
SELECT 'slvr_mi_actuals',           COUNT(*)    FROM slvr_mi_actuals;
-- demand_planning: ~850K   mi_actuals: ~265K
```

### Gold — key row counts
```sql
SELECT 'gold_gcm_base'         AS t, COUNT(*) AS n FROM gold_gcm_base
UNION ALL SELECT 'gold_cap_normal',    COUNT(*) FROM gold_cap_normal
UNION ALL SELECT 'gold_bottleneck',    COUNT(*) FROM gold_bottleneck
UNION ALL SELECT 'gold_ml_feature_store', COUNT(*) FROM gold_ml_feature_store;
-- 766319 / 1532638 / 73164 / 383128
```

### Gold — capacity math spot-check
```sql
-- Verify Step 3 formula: (H × 3600 × (1−A) × P) / step2
SELECT gcm_pk,
       ROUND(step3_productivity_adjusted, 4) AS step3,
       ROUND((hours_per_shift_normal * 3600
              * (1 - allowance_pct)
              * productivity_pct)
             / step2_total_avg_test_time, 4)  AS step3_manual
FROM gold_gcm_base LIMIT 5;
-- step3 and step3_manual must match exactly
```

### ML outputs
```sql
SELECT 'gold_demand_forecast'     AS t, COUNT(*) AS n FROM gold_demand_forecast
UNION ALL SELECT 'gold_yield_predictions', COUNT(*) FROM gold_yield_predictions
UNION ALL SELECT 'gold_maintenance_risk',  COUNT(*) FROM gold_maintenance_risk
UNION ALL SELECT 'gold_oee_anomalies',     COUNT(*) FROM gold_oee_anomalies
UNION ALL SELECT 'gold_capex_mc_summary',  COUNT(*) FROM gold_capex_mc_summary;
-- 5688 / 383128 / 265034 / 265034 / 181
```

---

## Smoke tests

| Test suite | Command | Expected |
|---|---|---|
| MCP server | `uv run python agentic/mcp_server/test_server.py` | 19/19 passed |
| Agent orchestrator | `uv run python agentic/agents/test_agents.py` | 10/10 passed |

---

## API health checks

```bash
# Chat backend
curl http://localhost:8000/api/health
# {"status":"ok","agents":["capacity","yield","maintenance","forecast","capex"],"version":"1.0.0"}

# Data Explorer
curl http://localhost:8001/explorer/api/sources | python -m json.tool | grep '"id"'
# Should list all 11 sources (10 SQLite + 1 DuckDB)
```

---

## ML model validation

```python
# Check yield prediction residuals
import duckdb
conn = duckdb.connect("data/capacity_planning_twin.duckdb", read_only=True)
conn.execute("""
    SELECT ROUND(AVG(abs_error_pp), 3)  AS mean_abs_error_pp,
           ROUND(MAX(abs_error_pp), 3)  AS max_abs_error_pp
    FROM gold_yield_predictions
""").df()
# mean_abs_error_pp: ~0.10   max: < 2.0
```

```python
# Check anomaly contamination rate
conn.execute("""
    SELECT ROUND(AVG(anomaly_flag) * 100, 1) AS anomaly_pct
    FROM gold_oee_anomalies
""").df()
# anomaly_pct: 5.0
```
