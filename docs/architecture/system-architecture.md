# System Architecture

---

## End-to-End Architecture

```mermaid
graph TB
    subgraph RAW["Raw Layer — 10 SQLite Databases"]
        R1[sites.db] 
        R2[products.db]
        R3[equipment.db]
        R4[demand.db]
        R5[yield_data.db]
        R6[oee_data.db]
        R7[calendar.db]
        R8[suppliers.db]
        R9[test_types.db]
        R10[gcm_config.db]
    end

    subgraph BRONZE["Bronze Layer — DuckDB (brnz_ prefix)"]
        B1[brnz_sites]
        B2[brnz_products]
        B3[brnz_equipment]
        B4[brnz_demand]
        B5[brnz_yield]
        B6[brnz_oee]
        B7[12 tables total · 2,751,592 rows]
    end

    subgraph SILVER["Silver Layer — DuckDB (slvr_ prefix)"]
        S1[slvr_gcm_reference]
        S2[slvr_demand_planning]
        S3[slvr_mi_actuals]
        S4[slvr_oee_actuals]
        S5[13 tables total · 3,119,383 rows]
    end

    subgraph GOLD["Gold Layer — DuckDB (gold_ + srv_vw_ prefix)"]
        G1[gold_gcm_base · 766K rows]
        G2[gold_cap_normal · 1.53M rows]
        G3[gold_cap_maximum · 1.53M rows]
        G4[gold_cap_actual · 6.16M rows]
        G5[gold_dmnd_vs_cap · 3.85M rows]
        G6[gold_bottleneck · 73K rows]
        G7[gold_oee_metrics · 7.6K rows]
        G8[gold_ml_feature_store · 383K rows]
        G9[6 serving views srv_vw_*]
    end

    subgraph ML["ML Layer — src/ml/"]
        M1[Demand Forecast · Prophet+XGB+LGB]
        M2[Yield Prediction · XGBoost+SHAP]
        M3[Predictive Maintenance · XGBoost+SMOTE]
        M4[OEE Anomaly · Isolation Forest]
        M5[CapEx Monte Carlo · 10K iterations]
        M6[gold_cap_ml_adjusted ← feedback]
    end

    subgraph AGENTIC["Agentic Layer — agentic/"]
        A1[MCP Server · 20 tools · stdio]
        A2[LangGraph Router]
        A3[CapacityAgent]
        A4[YieldAgent]
        A5[MaintenanceAgent]
        A6[ForecastAgent]
        A7[CapExAgent]
        A8[Ollama · llama3.1:8b]
    end

    subgraph API["API + UI Layer"]
        P1[FastAPI · port 8000 · SSE streaming]
        P2[FastAPI Explorer · port 8001]
        P3[Chat UI · frontend/]
        P4[Data Explorer · frontend/explorer/]
    end

    RAW -->|"PySpark ingest\nsrc/pipeline/bronze/ingest.py"| BRONZE
    BRONZE -->|"PySpark transforms\nsrc/pipeline/silver/"| SILVER
    SILVER -->|"5-step capacity math\nsrc/pipeline/gold/"| GOLD
    GOLD -->|"Feature store\ngold_ml_feature_store"| ML
    ML -->|"gold_cap_ml_adjusted\nyield feedback"| GOLD
    GOLD -->|"DuckDB read-only\nvia MCP tools"| A1
    A1 --> A2
    A2 --> A3 & A4 & A5 & A6 & A7
    A3 & A4 & A5 & A6 & A7 --> A8
    A8 --> P1
    P1 --> P3
    GOLD -->|"Direct DuckDB\nconnection"| P2
    P2 --> P4
```

---

## Execution Flow

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant Gen as Generators
    participant SQLite as SQLite (10 DBs)
    participant Bronze as Bronze Ingestion
    participant DuckDB as DuckDB
    participant Silver as Silver Transforms
    participant Gold as Gold Engine
    participant ML as ML Pipeline
    participant Ollama as Ollama
    participant API as FastAPI
    participant User as End User

    Dev->>Gen: uv run python -m src.generators.run_all_generators
    Gen->>SQLite: Generate 2.75M rows across 10 DBs

    Dev->>Bronze: uv run python -m src.pipeline.bronze.ingest
    Bronze->>SQLite: Read all source tables
    Bronze->>DuckDB: Write 12 brnz_ tables (validated, typed)

    Dev->>Silver: uv run python -m src.pipeline.silver.run_silver
    Silver->>DuckDB: Read brnz_ tables via PySpark
    Silver->>DuckDB: Write 13 slvr_ tables (joined, enriched)

    Dev->>Gold: uv run python -m src.pipeline.gold.run_gold
    Gold->>DuckDB: Read slvr_ tables
    Gold->>DuckDB: Write 9 gold_ tables + 6 srv_vw_ views

    Dev->>ML: uv run python -m src.ml.run_ml
    ML->>DuckDB: Read gold_ml_feature_store
    ML->>DuckDB: Write 11 ML output tables incl. gold_cap_ml_adjusted

    Dev->>Ollama: ollama serve (separate terminal)
    Dev->>API: uv run python -m backend.main

    User->>API: POST /api/chat/stream {"question": "..."}
    API->>DuckDB: Router classifies intent
    API->>Ollama: Domain agent selects tools
    Ollama-->>API: Tool call JSON
    API->>DuckDB: Execute MCP tool query
    DuckDB-->>API: Rows (JSON)
    API->>Ollama: Synthesize answer
    Ollama-->>API: Answer text (streamed)
    API-->>User: SSE stream (pipeline events + tokens)
```

---

## Data Flow Diagram

```mermaid
flowchart LR
    subgraph SOURCES["Source Systems (Synthetic)"]
        direction TB
        S1[Sites & Suppliers]
        S2[Products & Families]
        S3[Equipment Specs]
        S4[Demand Plans]
        S5[Yield Records]
        S6[OEE Records]
        S7[Calendar]
        S8[GCM Config]
    end

    subgraph PIPELINE["Data Pipeline"]
        direction TB
        B["Bronze\nSchema validation\nType casting\nNull checks\nDedup"]
        SL["Silver\nJoins & enrichment\nMonth/year features\nLag features\nNPI flags\nYield forward-fill"]
        G["Gold\n5-step capacity math\nBottleneck classification\nOEE metrics\nML feature store\nServing views"]
    end

    subgraph MLPIPE["ML Pipeline"]
        direction TB
        M1["Demand Forecast\nProphet+XGB+LGB ensemble\nCroston for NPI"]
        M2["Yield Prediction\nXGBoost + SHAP\n→ capacity feedback"]
        M3["Predictive Maintenance\nXGBoost + SMOTE"]
        M4["OEE Anomaly\nIsolation Forest"]
        M5["CapEx Monte Carlo\n10K simulations\nP50/P80/P95"]
    end

    subgraph SERVING["Serving Layer"]
        direction TB
        A["MCP Server\n20 tools\nRead-only DuckDB"]
        AG["5 Domain Agents\nLangGraph\nllama3.1:8b"]
        API2["FastAPI\nSSE streaming"]
    end

    SOURCES --> PIPELINE
    PIPELINE --> MLPIPE
    MLPIPE -.->|yield feedback| PIPELINE
    PIPELINE --> SERVING
    MLPIPE --> SERVING
```

---

## LangGraph Agent Graph

```mermaid
stateDiagram-v2
    [*] --> Router : User message

    Router --> CapacityAgent : agent = "capacity"
    Router --> YieldAgent : agent = "yield"
    Router --> MaintenanceAgent : agent = "maintenance"
    Router --> ForecastAgent : agent = "forecast"
    Router --> CapExAgent : agent = "capex"

    CapacityAgent --> [*] : answer + tool_results
    YieldAgent --> [*] : answer + tool_results
    MaintenanceAgent --> [*] : answer + tool_results
    ForecastAgent --> [*] : answer + tool_results
    CapExAgent --> [*] : answer + tool_results

    note right of Router
        ChatOllama (llama3.1:8b)
        temperature=0.0
        num_predict=64
        Outputs: domain name
    end note

    note right of CapacityAgent
        1. Tool selection (LLM call)
        2. Tool execution (MCP → DuckDB)
        3. Synthesis (LLM call)
    end note
```

---

## MCP Communication Flow

```mermaid
sequenceDiagram
    participant Agent as Domain Agent (Python)
    participant MCP as MCP Server (server.py)
    participant Tool as Tool Function
    participant DuckDB as DuckDB (read-only)

    Note over Agent,DuckDB: Tools are called directly (same process, not stdio in agent context)

    Agent->>MCP: tool_fn(**args)
    MCP->>Tool: Dispatch to tools/capacity_tools.py etc.
    Tool->>DuckDB: parameterised SELECT query
    DuckDB-->>Tool: rows as list[dict]
    Tool-->>MCP: {"columns": [...], "rows": [...], "row_count": N}
    MCP-->>Agent: result dict

    Note over Agent: Agent passes result to synthesis LLM
```

> **Note**: The MCP server implements the JSON-RPC 2.0 stdio protocol for Claude Desktop compatibility, but within the LangGraph agentic system, tool functions are called directly as Python callables — the stdio transport is used only when connecting via external MCP clients (e.g. Claude Desktop).

---

## Database Architecture

All data lives in **one DuckDB file**: `data/capacity_planning_twin.duckdb`, schema `main`.

```mermaid
erDiagram
    BRONZE {
        varchar brnz_sites_pk PK
        varchar brnz_products_pk PK
        varchar brnz_equipment_pk PK
        varchar brnz_demand_pk PK
    }

    SILVER {
        varchar slvr_gcm_reference_pk PK
        varchar slvr_demand_planning_pk PK
        varchar slvr_mi_actuals_pk PK
    }

    GOLD_GCM_BASE {
        varchar gcm_pk PK
        varchar site_code FK
        varchar product_number FK
        varchar test_type FK
        integer month_key
        double target_yield
        double step1
        double step2
        double step3
        double step4
    }

    GOLD_CAP_NORMAL {
        varchar cap_pk PK
        varchar gcm_pk FK
        double capacity_qty
        double utilization_pct
        double gap_pct
        varchar bottleneck_severity
    }

    GOLD_ML_FEATURE_STORE {
        varchar feat_pk PK
        varchar site_code FK
        varchar product_number FK
        varchar test_type FK
        integer month_key
        double demand_qty
        double target_yield
        double oee_pct
    }

    SILVER ||--o{ GOLD_GCM_BASE : "transforms into"
    GOLD_GCM_BASE ||--o{ GOLD_CAP_NORMAL : "capacity math"
    GOLD_GCM_BASE ||--o{ GOLD_ML_FEATURE_STORE : "feature engineering"
```

---

## Layer Prefix Convention

| Prefix | Layer | Example |
|---|---|---|
| `brnz_` | Bronze | `brnz_sites`, `brnz_products` |
| `slvr_` | Silver | `slvr_gcm_reference`, `slvr_demand_planning` |
| `gold_` | Gold (tables) | `gold_gcm_base`, `gold_bottleneck` |
| `srv_vw_` | Gold (serving views) | `srv_vw_capacity_summary`, `srv_vw_bottleneck_heatmap` |
