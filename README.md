# Test Equipment Capacity Planning Digital Twin

A local learning project for telecom and networking manufacturing. It combines synthetic source systems, data engineering, capacity planning, operations analytics, ML, and a grounded local AI assistant.

All required technologies are free and open source. The target is one Windows computer with 16 GB RAM.

## Applications

| Application | Purpose |
|---|---|
| Capacity Home | Opens every workspace and shows health |
| Data Explorer | Browses every Raw, Reference, Mapping, Bronze, Silver, Gold, Serving, and ML object |
| Capacity Analysis | Compares Normal, Maximum, Actual Output, and Demonstrated Capacity |
| Decision Intelligence | Runs and explains five ML workflows |
| Data Operations | Generates Raw data, runs the medallion pipeline, and shows lineage |
| Documentation | Reads these Markdown files directly |

Yukti is available from the top navigation on every page. It uses the current page, selected workflow, filters, and selected table as context. Yukti can use only server-approved read-only tools.

## Data architecture

The source bundle contains:

- 7 Raw SQLite databases with 18 source tables
- One governed Reference DuckDB database
- One governed Mapping DuckDB database

Each pipeline run publishes:

- One Bronze DuckDB database with 18 tables
- One Silver DuckDB database with 22 tables
- One Gold DuckDB database with 14 tables
- One Serving DuckDB database with 19 tables
- One ML DuckDB database with 12 tables

`release_current.json` selects one compatible source, pipeline, Serving, and ML release. Generated files remain outside the repository under `CAPACITY_TWIN_HOME`.

## Business scope

- Synthetic brand: Erivon
- Domain: telecom and networking test equipment capacity
- Actual data end date: 2026-10-31
- Forecast start date: 2026-11-01
- Explicit demand classes: `DIRECT_CUSTOMER`, `SPARE`, `SERVICE`, `BOM_DEPENDENT`
- Explicit resource behavior: alternative, serial, paired fixture, multi-DUT, standalone, shared, and dedicated
- Intentional Raw noise: duplicates, nulls, missing dates, outliers, stale values, and broken references

Real company names are reference examples only. All capabilities, products, volumes, routes, and performance are synthetic.

## Quick start

Requirements:

- Python 3.12
- uv
- Java 17
- Ollama only when Yukti is needed

```powershell
# Install locked dependencies and development tools.
uv sync --extra dev

# Keep generated files outside the repository.
$env:CAPACITY_TWIN_HOME = "$env:LOCALAPPDATA\CapacityPlanningDigitalTwin"

# Build data and ML publications in order.
uv run capacity-generate
uv run capacity-pipeline
uv run capacity-ml

# Start the complete local application.
uv run capacity-twin
```

Optional Yukti model:

```powershell
# Download the local baseline model.
ollama pull llama3.1:8b

# Start the Ollama service.
ollama serve
```

Open `http://127.0.0.1:8000`.

## Documentation

- [Install](docs/setup/installation.md)
- [Run](docs/setup/running.md)
- [System architecture](docs/architecture/system-architecture.md)
- [Data generation](docs/data-engineering/data-generation.md)
- [Pipeline](docs/data-engineering/pipeline-overview.md)
- [ML](docs/ml/ml-overview.md)
- [Validation](docs/setup/validation.md)
- [Limitations](docs/setup/limitations.md)
- [Future scope](docs/technical-reference/future-scope.md)

The Documentation app reads the same Markdown files. There is no second content copy.

> Educational and synthetic. Do not use outputs for real operational, safety, staffing, procurement, or investment decisions.
