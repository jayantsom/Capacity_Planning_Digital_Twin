# Configuration

> All runtime configuration lives in `config/settings.yaml`. No `.env` file is used.

---

## `config/settings.yaml`

```yaml
databases:
  raw_dir:    data/                              # SQLite source databases
  analytics:  data/capacity_planning_twin.duckdb # Single DuckDB file

pipeline:
  bronze:
    batch_size: 10000
  silver:
    spark_master: local[*]                       # Change to cluster URL for distributed
    jdbc_url: jdbc:duckdb:data/capacity_planning_twin.duckdb
  gold:
    allowance_pct:    0.10                       # Step 3 — locked constant
    productivity_pct: 0.95                       # Step 3 — locked constant

agentic:
  llm_provider:    ollama
  ollama_base_url: http://localhost:11434
  default_model:   llama3.1:8b
  router_model:    llama3.1:8b
  temperature:     0.1
  max_tokens:      4096
  streaming:       true

logging:
  level:     INFO
  log_dir:   logs/
  rotation:  10 MB
  retention: 30 days
```

---

## Key constants (locked — do not change)

| Constant | Value | Where used |
|---|---|---|
| `OtherImpediments` | 0 | All capacity math |
| `retest_times` (Type 1) | 2.0 | `gcm_base.py`, `yield_prediction.py` |
| `test_x_param` (Type 1) | 0.75 | Same |
| `FAILURE_THRESHOLD_OEE` | 0.88 | `predictive_maintenance.py` |
| `N_SIMULATIONS` | 10,000 | `capex_montecarlo.py` |
| `FORECAST_HORIZON` | 18 months | `demand_forecast.py` |
| `BACKTEST_MONTHS` | 6 | `demand_forecast.py` |
| `CONTAMINATION` | 0.05 | `oee_anomaly.py` |

---

## Path resolution pattern

All modules resolve the project root relative to their own `__file__`:

| Module location | Pattern | `parents[N]` |
|---|---|---|
| `src/utils/ml_utils.py` | `Path(__file__).resolve().parents[2]` | 2 |
| `agentic/mcp_server/db.py` | `Path(__file__).resolve().parents[2]` | 2 |
| `backend/main.py` | `Path(__file__).resolve().parents[1]` | 1 |

**Why not `os.getcwd()`?** Working directory varies by how the module is invoked (`uv run`, IDE, test runner). `__file__`-relative paths are invariant.

---

## Logger import pattern

```python
# Correct — everywhere in the codebase
from src.utils.logger import logger as log

# Wrong — bypasses configured handlers
from loguru import logger
```

`src/utils/logger.py` calls `setup_logger()` on import, which adds the file handler with rotation. Direct loguru import skips this setup.
