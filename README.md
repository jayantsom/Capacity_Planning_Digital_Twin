# Capacity Planning Digital Twin

A local, synthetic telecom and networking manufacturing capacity-planning project. It combines deterministic data generation, a Raw-to-Serving medallion pipeline, five existing ML workflows, and Operations Assistant, a local LangGraph assistant grounded in read-only data tools.

All technologies are free and open source. The target is one Windows workstation with 16 GB RAM; generated data, models, logs, and run artifacts stay outside the repository.

## Essential project

- **Domain:** telecom and networking products, routes, tests, sites, resources, demand, yield, OEE, capacity, and CapEx.
- **Synthetic brand:** **Erivon**, with `ERV_*` identifiers. Real manufacturer or EMS names may appear only as attributed educational reference data; no real capability, volume, performance, or affiliation is implied.
- **Dates:** actual and execution data cover 2023-01-01 through 2026-10-31. Forecast data cover 2026-11-01 through 2027-12-31. Each planning version observes only actuals known by its as-of date.
- **Demand:** `DIRECT_CUSTOMER`, `SPARE`, `SERVICE`, and `BOM_DEPENDENT` are explicit. Parent BOM demand and independent child demand remain separately reconcilable.
- **Equipment:** routes declare `ALTERNATIVE_POOL`, `SERIAL_STEP`, `PAIRED_FIXTURE`, `MULTI_DUT`, `STANDALONE`, `SHARED_POOL`, or `DEDICATED` behavior.
- **Raw quality:** intentional duplicates, nulls, missing days, outliers, late records, stale dimensions, and broken references must be named by noise rules and traceable to expected outcomes.
- **Publication:** candidate runs are validated before promotion; manifests record schemas, checksums, counts, reconciliations, validation results, and promotion state. These are target contracts where implementation is still being stabilized.

No fixed row counts, runtimes, model scores, or business-quality claims are made here. Results depend on the selected profile, machine, seed, and validated run.

## Five applications and one shared core

| Component | Responsibility | Configuration |
|---|---|---|
| Capacity Home | Compact launcher for all four workspaces | `capacity_home/config.yaml` |
| Operations Assistant | Assistant, agents, MCP tools, and local API | `operations_assistant/config.yaml` |
| Data Explorer | Read-only table and query interface | `data_explorer/config.yaml` |
| Data Operations | Generator and medallion-pipeline tabs with safe local jobs | `data_operations/config.yaml` |
| Decision Intelligence | Five ML dashboards and atomic model publication | `decision_intelligence/config.yaml` |
| Capacity Twin Core | Shared paths, dates, contracts, logging, and capacity formulas | `src/capacity_twin_core/config.yaml` |

The landing page shows **Data Explorer**, **Decision Intelligence**, and **Operations Assistant** in the first row, followed by **Data Operations**. The UI uses a light Graphite/Dark Cyan identity and plain HTML, CSS, and JavaScript. One FastAPI server on `127.0.0.1` serves every workspace and API.

## Storage

Set `CAPACITY_TWIN_HOME` to keep runtime data outside the checkout. On Windows the default is `%LOCALAPPDATA%\CapacityPlanningDigitalTwin`.

- Ten Raw source databases are separate SQLite files.
- Application-owned mappings and analytical windows are published separately in `control_reference.duckdb`.
- Processed layers are separate `bronze.duckdb`, `silver.duckdb`, `gold.duckdb`, `ml.duckdb`, and `serving.duckdb` files in the approved run-artifact design.
- `control_current.json`, `raw_current.json`, `current.json`, and `ml_current.json` identify the active lineage.
- Operations Assistant and Data Explorer are read-only consumers of promoted data.

Pipeline candidates use separate run-scoped databases. Validation must pass before `current.json` is atomically changed to the new promoted run.

## Quick start

Python 3.12, uv, Java 17 for PySpark, and optional Ollama are required.

```powershell
# Install the locked project and development tools.
uv sync --extra dev

# Optionally choose an external runtime directory.
$env:CAPACITY_TWIN_HOME = "$env:LOCALAPPDATA\CapacityPlanningDigitalTwin"

# Generate Raw data, build the pipeline, and run the five ML workflows.
uv run capacity-generate
uv run capacity-pipeline
uv run capacity-ml

# Start every dashboard on one local address.
uv run capacity-twin
```

Operations Assistant uses `llama3.1:8b` through local Ollama as its baseline. Data Explorer should remain usable when Ollama is unavailable.

```powershell
# Pull and run the optional local model.
ollama pull llama3.1:8b
ollama serve
```

## ML scope

The project retains five workflows: demand forecasting, measured-yield prediction, OEE degradation risk, OEE anomaly detection, and CapEx Monte Carlo simulation. Evaluation must be temporal and leakage-aware, with train, validation, and holdout windows separated by month and honest comparison to a declared naive baseline. Weekly analytics are limited to operational facts derived from daily execution/events; monthly planning or ML values are never converted into artificial weeks. A workflow that cannot be evaluated returns `not_evaluable` with a reason. CapEx is simulation, not optimization, and contamination is not model accuracy.

## Documentation

- [Architecture](docs/architecture/system-architecture.md)
- [Configuration](docs/architecture/configuration.md)
- [Data generation](docs/data-engineering/data-generation.md)
- [Pipeline](docs/data-engineering/pipeline-overview.md)
- [ML workflows](docs/ml/ml-overview.md)
- [Operations Assistant and APIs](docs/ai-enablement/agentic-architecture.md)
- [Installation](docs/setup/installation.md)
- [Running](docs/setup/running.md)
- [Validation](docs/setup/validation.md)
- [Limitations](docs/setup/limitations.md)
- [Future scope](docs/technical-reference/future-scope.md)
- [Disclaimer and license](docs/technical-reference/license.md)

## Future alternatives

Future model evaluation may compare licensed Ollama tags for a Qwen 3.5 4B-class candidate, Granite 4.2 8B-class candidate, and Qwen 3.5 9B-class challenger. Exact tags, availability, licenses, latency, RAM, and tool-call quality must be verified first. `llama.cpp` is the preferred lightweight runtime alternative; LocalAI and vLLM remain conditional future options.

> This project is educational and synthetic. Do not use its outputs for production decisions.
