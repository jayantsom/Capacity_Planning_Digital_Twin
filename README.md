# Capacity Planning Digital Twin

[![Python](https://img.shields.io/badge/Python-3.12.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![DuckDB](https://img.shields.io/badge/DuckDB-Analytics_DB-FFF000?logo=duckdb&logoColor=black)](https://duckdb.org)
[![PySpark](https://img.shields.io/badge/PySpark-4.1.2-E25A1C?logo=apachespark&logoColor=white)](https://spark.apache.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-1C3C3C?logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph)
[![Ollama](https://img.shields.io/badge/Ollama-llama3.1:8b-000000?logo=ollama&logoColor=white)](https://ollama.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![uv](https://img.shields.io/badge/uv-Package_Manager-DE5FE9)](https://docs.astral.sh/uv)
[![License](https://img.shields.io/badge/License-Personal_Portfolio-lightgrey)](./docs/technical-reference/license.md)

> **A local end-to-end semiconductor manufacturing capacity planning system** combining a medallion data pipeline, deterministic capacity math, five ML models, and a LangGraph multi-agent AI framework for natural-language analytics.

---

## TL;DR

This project builds a **capacity planning digital twin** for a synthetic semiconductor/telecom test-equipment manufacturing environment. It ingests raw operational data from 10 SQLite databases, processes it through a Bronze → Silver → Gold medallion pipeline using PySpark and DuckDB, applies a validated 5-step capacity utilisation engine, trains five domain-specific ML models, and exposes the entire gold layer through a multi-agent AI system where a local LLM routes natural-language queries to specialised domain agents.

**Everything runs locally.** No cloud dependencies. No paid APIs.

---

## What This System Does

| Layer | What it does | Output |
|---|---|---|
| **Raw** | 10 SQLite DBs, 2.75M rows of synthetic operational data | Source of truth |
| **Bronze** | Ingests + validates all raw data into DuckDB | 12 tables, 2,751,592 rows |
| **Silver** | PySpark transforms: joins, enrichments, feature engineering | 13 tables, 3,119,383 rows |
| **Gold** | 5-step capacity math engine + analytics aggregations | 9 tables + 6 serving views |
| **ML** | 5 models: demand forecasting, yield prediction, predictive maintenance, anomaly detection, CapEx optimisation | 11 output tables |
| **Agentic** | LangGraph router + 5 domain agents + MCP server + FastAPI + UI | Natural-language capacity analytics |

---

## Motivation

Capacity planning in semiconductor/telecom manufacturing is a complex, multi-variable problem involving equipment utilisation, yield rates, demand variability, and capital expenditure decisions. Traditional approaches rely on static spreadsheet models that cannot incorporate ML-predicted yield, probabilistic demand, or natural-language querying.

This project demonstrates the full engineering stack required to build an AI-enabled capacity planning system — from raw data modelling through to a conversational analytics interface — matching the technical depth required for Advanced Analytics & AI Enablement roles in semiconductor manufacturing.

---

## Features

- **Medallion data architecture**: Raw → Bronze → Silver → Gold, all in a single DuckDB file with layer-prefixed tables
- **Deterministic 5-step capacity math engine**: Mathematically validated to 4 decimal places, implementing industry-standard test equipment capacity formulas
- **Two retest models**: Type 1 (fixed retest parameters) and Type 2 (yield-based retest calculation)
- **Semiconductor-standard bottleneck classification**: Six severity tiers (CRITICAL / HIGH / MEDIUM / LOW / BALANCED / EXCESS)
- **Five ML models**: Prophet+XGBoost+LightGBM demand ensemble, XGBoost yield regressor with SHAP, SMOTE-balanced failure classifier, Isolation Forest OEE anomaly detector, Monte Carlo CapEx optimiser
- **ML yield feedback loop**: Predicted yield feeds back into the capacity math engine via `gold_cap_ml_adjusted`
- **LangGraph multi-agent framework**: Router + 5 domain agents (Capacity, Yield, Maintenance, Forecast, CapEx)
- **MCP server**: 20 structured tools exposing the DuckDB gold layer, plus a safe fallback `run_query` tool
- **Streaming FastAPI backend**: SSE streaming with per-step pipeline events
- **Data Explorer**: Separate FastAPI app on port 8001 with full SQLite + DuckDB browser, Chart.js visualisations, SQL editor, CSV export, dark/light mode
- **Fully local**: llama3.1:8b via Ollama, no external API calls

---

## Documentation Index

### Architecture
- [System Architecture](./docs/architecture/system-architecture.md) — end-to-end architecture, execution flow, Mermaid diagrams
- [File Structure](./docs/architecture/file-structure.md) — every file and directory explained
- [Tech Stack](./docs/architecture/tech-stack.md) — detailed technology table with justifications
- [Configuration](./docs/architecture/configuration.md) — settings.yaml, constants.py, environment

### Technical & Industrial Engineering
- [Capacity Planning Fundamentals](./docs/technical-reference/capacity-planning.md) — domain concepts, terminology, formulas, worked examples
- [Data Scope & Schema](./docs/technical-reference/data-scope.md) — sites, products, test types, data ranges

### Data Engineering
- [Pipeline Overview](./docs/data-engineering/pipeline-overview.md) — medallion architecture, end-to-end data flow
- [Synthetic Data Generation](./docs/data-engineering/data-generation.md) — all 10 generators, logic, schemas
- [Bronze Layer](./docs/data-engineering/bronze.md) — ingestion, validation, schema
- [Silver Layer](./docs/data-engineering/silver.md) — PySpark transforms, enrichment, feature engineering
- [Gold Layer](./docs/data-engineering/gold.md) — capacity math, analytics, serving views

### Machine Learning
- [ML Overview](./docs/ml/ml-overview.md) — model registry, feature store, design decisions
- [Demand Forecasting](./docs/ml/demand-forecasting.md) — Prophet + XGBoost + LightGBM ensemble + Croston
- [Yield Prediction](./docs/ml/yield-prediction.md) — XGBoost regressor + SHAP + capacity feedback
- [Predictive Maintenance](./docs/ml/predictive-maintenance.md) — XGBoost classifier + SMOTE
- [OEE Anomaly Detection](./docs/ml/oee-anomaly.md) — Isolation Forest
- [CapEx Optimisation](./docs/ml/capex-montecarlo.md) — Monte Carlo simulation

### AI Enablement
- [Agentic Architecture](./docs/ai-enablement/agentic-architecture.md) — LangGraph graph, state, routing
- [MCP Server](./docs/ai-enablement/mcp-server.md) — tool registry, protocol, all 20 tools
- [Domain Agents](./docs/ai-enablement/agents.md) — all 5 agents, prompts, tool bindings
- [FastAPI Backend](./docs/ai-enablement/backend.md) — endpoints, SSE streaming, data explorer

### Setup & Operations
- [Installation](./docs/setup/installation.md) — prerequisites, uv setup, dependencies
- [Running the Project](./docs/setup/running.md) — all run commands, expected outputs
- [Validation & Testing](./docs/setup/validation.md) — smoke tests, verification queries
- [Known Limitations](./docs/setup/limitations.md) — current constraints and workarounds

### Reference
- [Glossary](./docs/technical-reference/glossary.md) — every technical term defined
- [Future Scope](./docs/technical-reference/future-scope.md)
- [Disclaimer & License](./docs/technical-reference/license.md)

---

## Quick Start

```bash
# 1. Clone and set up
git clone <repo>
cd capacity_planning_digital_twin
uv sync

# 2. Run the full pipeline
uv run python -m src.generators.run_all_generators   # ~2 min
uv run python -m src.pipeline.bronze.ingest          # ~30s
uv run python -m src.pipeline.silver.run_silver      # ~135s
uv run python -m src.pipeline.gold.run_gold          # ~60s
uv run python -m src.ml.run_ml                       # ~15 min

# 3. Start Ollama (separate terminal)
ollama serve
ollama pull llama3.1:8b

# 4. Start backends
uv run python -m backend.main                        # port 8000 — AI chat
uv run uvicorn backend.explorer.main:app --port 8001 # port 8001 — Data Explorer

# 5. Open
# http://localhost:8000   → AI Analyst chat
# http://localhost:8001/explorer/ → Data Explorer
```

---

## Author

**Jayant Som**
Data & AI-ML Consultant · MS Electrical Engineering (University at Buffalo, GPA 3.87)

[![LinkedIn](https://img.shields.io/badge/LinkedIn-jayantsom-0077B5?logo=linkedin)](https://www.linkedin.com/in/jayantsom)
[![Email](https://img.shields.io/badge/Email-jayant4195@gmail.com-D14836?logo=gmail&logoColor=white)](mailto:jayant4195@gmail.com)

---

> **Disclaimer**: See [Disclaimer & License](./docs/technical-reference/license.md).
