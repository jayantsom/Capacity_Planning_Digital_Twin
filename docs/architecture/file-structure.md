# File Structure

> Every file and directory in the project, with purpose and key relationships.

---

```
capacity_planning_digital_twin/
│
├── README.md                          ← Project overview, quick start, docs index
├── pyproject.toml                     ← uv dependencies, Python version constraint
├── .python-version                    ← Pins Python 3.12.12 for uv
│
├── config/
│   └── settings.yaml                 ← All runtime configuration (see Configuration doc)
│
├── data/                             ← All data files (not committed to git)
│   ├── sites.db                      ← Raw SQLite: 22 sites
│   ├── suppliers.db                  ← Raw SQLite: 6 suppliers
│   ├── products.db                   ← Raw SQLite: 35 products + hierarchy
│   ├── equipment.db                  ← Raw SQLite: equipment specs + site mapping
│   ├── test_types.db                 ← Raw SQLite: 10 test type definitions
│   ├── calendar.db                   ← Raw SQLite: monthly calendar Jan 2023–Dec 2027
│   ├── gcm_config.db                 ← Raw SQLite: GCM operational parameters
│   ├── demand.db                     ← Raw SQLite: monthly demand per product×site×snapshot
│   ├── yield_data.db                 ← Raw SQLite: monthly yield per product×test_type×site
│   ├── oee_data.db                   ← Raw SQLite: monthly OEE per site×test_type
│   └── capacity_planning_twin.duckdb ← Single DuckDB file: all Bronze/Silver/Gold layers
│
├── models/                           ← Pickled ML models (auto-created by src/ml/run_ml.py)
│   ├── demand_xgb.pkl                ← XGBoost demand forecaster
│   ├── demand_xgb_meta.json          ← Feature list + training metadata
│   ├── demand_lgbm.pkl               ← LightGBM demand forecaster
│   ├── yield_xgb.pkl                 ← XGBoost yield regressor
│   ├── yield_xgb_meta.json
│   ├── maintenance_xgb.pkl           ← XGBoost failure classifier
│   ├── maintenance_xgb_meta.json
│   └── oee_isolation_forest.pkl      ← Dict: {isolation_forest, scaler}
│
├── logs/                             ← Loguru rotating logs (auto-created)
│   └── pipeline_YYYY-MM-DD.log
│
├── src/
│   ├── __init__.py
│   │
│   ├── generators/                   ← Raw data generation
│   │   ├── __init__.py
│   │   ├── run_all_generators.py     ← Entry point: runs all 10 in dependency order
│   │   ├── sites_generator.py
│   │   ├── suppliers_generator.py
│   │   ├── products_generator.py
│   │   ├── equipment_generator.py
│   │   ├── test_types_generator.py
│   │   ├── calendar_generator.py
│   │   ├── gcm_config_generator.py
│   │   ├── demand_generator.py
│   │   ├── yield_generator.py
│   │   └── oee_generator.py
│   │
│   ├── pipeline/
│   │   ├── __init__.py
│   │   │
│   │   ├── bronze/
│   │   │   ├── __init__.py
│   │   │   ├── schema.py             ← BRONZE_SCHEMAS: column specs, types, null rules
│   │   │   └── ingest.py             ← Read SQLite → validate → cast → dedup → write DuckDB
│   │   │
│   │   ├── silver/
│   │   │   ├── __init__.py
│   │   │   ├── run_silver.py         ← Entry point: runs all 3 transform modules in order
│   │   │   ├── transforms_reference.py ← GCM config × product × equipment master join
│   │   │   ├── transforms_planning.py  ← Demand × hierarchy × lag features
│   │   │   ├── transforms_mi.py        ← OEE × yield actuals × feature engineering
│   │   │   └── utils.py              ← Spark helpers; stack() type-cast fix
│   │   │
│   │   └── gold/
│   │       ├── __init__.py
│   │       ├── run_gold.py           ← Entry point: runs gcm_base → capacity_math → analytics → serving_views
│   │       ├── gcm_base.py           ← Builds gold_gcm_base; pre-computes Steps 1–4
│   │       ├── capacity_math.py      ← Step 5; writes gold_cap_normal/maximum/actual
│   │       ├── analytics.py          ← gold_dmnd_vs_cap, gold_bottleneck, gold_oee_metrics,
│   │       │                            gold_forecast_accuracy, gold_ml_feature_store
│   │       ├── serving_views.py      ← 6 srv_vw_ views
│   │       └── utils.py              ← Gold layer SQL helpers
│   │
│   ├── ml/
│   │   ├── __init__.py
│   │   ├── run_ml.py                 ← Entry point: runs all 5 priorities in sequence
│   │   └── models/
│   │       ├── __init__.py
│   │       ├── demand_forecast.py    ← Priority 1: Prophet+XGB+LGB ensemble + Croston
│   │       ├── yield_prediction.py   ← Priority 2: XGBoost regressor + SHAP + feedback
│   │       ├── predictive_maintenance.py ← Priority 3: XGBoost classifier + SMOTE
│   │       ├── oee_anomaly.py        ← Priority 4: Isolation Forest
│   │       └── capex_montecarlo.py   ← Priority 5: 10K Monte Carlo simulations
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logger.py                 ← Loguru setup: setup_logger() + exports `logger`
│       ├── db_utils.py               ← DuckDB connection helper for pipeline modules
│       ├── spark_utils.py            ← SparkSession factory for Silver layer
│       ├── month_utils.py            ← month_label_to_key() and related helpers
│       └── ml_utils.py               ← Shared ML utils: get_conn(), load_feature_store(),
│                                        upsert_table(), save_model(), lag/rolling helpers,
│                                        mape/smape/rmse metrics
│
├── agentic/
│   ├── __init__.py
│   │
│   ├── mcp_server/
│   │   ├── __init__.py
│   │   ├── server.py                 ← stdio JSON-RPC entry point; TOOL_REGISTRY dict
│   │   ├── db.py                     ← Shared read-only DuckDB connection; query() helper
│   │   ├── test_server.py            ← 19-test smoke suite
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── schema_tools.py       ← list_tables, get_schema, get_table_preview, get_distinct_values
│   │       ├── capacity_tools.py     ← get_capacity_summary, get_bottleneck_analysis,
│   │       │                            get_demand_vs_supply, get_equipment_utilization
│   │       ├── yield_tools.py        ← get_yield_prediction, get_yield_drivers, get_ml_adjusted_capacity
│   │       ├── maintenance_tools.py  ← get_maintenance_alerts, get_failure_risk_trend
│   │       ├── forecast_tools.py     ← get_demand_forecast, get_forecast_accuracy
│   │       ├── capex_tools.py        ← get_capex_recommendation, get_capex_scenarios
│   │       └── query_tool.py         ← run_query (fallback; SQL guard + read_only)
│   │
│   └── agents/
│       ├── __init__.py
│       ├── config.py                 ← ChatOllama factory; settings.yaml reader
│       ├── state.py                  ← AgentState TypedDict
│       ├── router.py                 ← router_node() + route_to_agent() edge function
│       ├── base_agent.py             ← BaseAgent: tool selection → execution → synthesis
│       ├── domain_agents.py          ← 5 agent classes + AGENT_REGISTRY
│       ├── orchestrator.py           ← Compiled LangGraph graph; ask(); ask_stream()
│       └── test_agents.py            ← 10-test end-to-end suite
│
├── backend/
│   ├── __init__.py
│   ├── main.py                       ← FastAPI app port 8000; /api/chat/stream SSE
│   ├── models.py                     ← Pydantic: ChatRequest, ChatResponse, ToolResult, PipelineStep
│   └── explorer/
│       ├── __init__.py
│       └── main.py                   ← FastAPI app port 8001; Data Explorer REST API
│
├── frontend/
│   ├── index.html                    ← Chat UI shell
│   ├── style.css                     ← IBM Plex fonts; deep navy palette; agent color codes
│   ├── app.js                        ← SSE consumer; pipeline trace; markdown renderer
│   └── explorer/
│       ├── index.html                ← Data Explorer shell
│       ├── explorer.css              ← Dark/light themes; layer color stripes
│       └── explorer.js               ← Sidebar; filters; table; Chart.js; SQL editor
│
└── docs/
    ├── architecture/
    │   ├── system-architecture.md
    │   ├── tech-stack.md
    │   ├── file-structure.md         ← This file
    │   └── configuration.md
    ├── data-engineering/
    │   ├── pipeline-overview.md
    │   ├── data-generation.md
    │   ├── bronze.md
    │   ├── silver.md
    │   └── gold.md
    ├── ml/
    │   ├── ml-overview.md
    │   ├── demand-forecasting.md
    │   ├── yield-prediction.md
    │   ├── predictive-maintenance.md
    │   ├── oee-anomaly.md
    │   └── capex-montecarlo.md
    ├── ai-enablement/
    │   ├── agentic-architecture.md
    │   ├── mcp-server.md
    │   ├── agents.md
    │   └── backend.md
    ├── setup/
    │   ├── installation.md
    │   ├── running.md
    │   ├── validation.md
    │   └── limitations.md
    └── technical-reference/
        ├── capacity-planning.md
        ├── data-scope.md
        ├── glossary.md
        ├── future-scope.md
        └── license.md
```

---

## Key cross-file dependencies

| File | Depends on |
|---|---|
| `src/ml/models/*.py` | `src/utils/ml_utils.py` (connection, helpers), `src/utils/logger.py` |
| `src/pipeline/gold/*.py` | `src/pipeline/silver/` tables in DuckDB, `src/utils/logger.py` |
| `agentic/agents/*.py` | `agentic/mcp_server/tools/*.py` (direct imports), `config/settings.yaml` |
| `agentic/mcp_server/tools/*.py` | `agentic/mcp_server/db.py` |
| `backend/main.py` | `agentic/agents/orchestrator.py`, `agentic/agents/domain_agents.py` |
| `backend/explorer/main.py` | `data/*.db`, `data/capacity_planning_twin.duckdb` |

## Naming conventions

| Prefix/Suffix | Meaning |
|---|---|
| `brnz_` | Bronze DuckDB table |
| `slvr_` | Silver DuckDB table |
| `gold_` | Gold DuckDB table |
| `srv_vw_` | Gold serving view |
| `run_*.py` | Pipeline entry point |
| `transforms_*.py` | Silver transform module |
| `*_tools.py` | MCP tool file |
| `*_generator.py` | Raw data generator |
| `*_meta.json` | ML model metadata sidecar |
