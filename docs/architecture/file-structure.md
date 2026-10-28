# File Structure

## Repository

| Path | Ownership |
|---|---|
| `capacity_home/` | Application launcher |
| `operations_assistant/` | Shared Yukti engine, agents, and tools |
| `data_explorer/` | Read-only browser and query UI |
| `capacity_analysis/` | Tactical capacity and bottleneck analysis |
| `decision_intelligence/` | Five ML workflows, dashboards, publication, and tests |
| `data_operations/` | Generator, pipeline, architecture, configuration, and tests |
| `documentation/` | Markdown-backed documentation app |
| `src/capacity_twin_core/` | Shared runtime paths, dates, logging, contracts, formulas, and fixtures |
| `docs/` | Project documentation |
| `pyproject.toml`, `uv.lock` | Package metadata and locked environment |

Each app owns `config.yaml` and its private implementation. An app may use published
Capacity Twin Core contracts but must not import another app’s private internals.

Current executable paths include:

- `data_operations/generator/generators/run_all_generators.py`
- `data_operations/pipeline/runner.py`
- `decision_intelligence/ml/run_ml.py`
- `operations_assistant/backend/main.py`
- `data_explorer/backend/main.py`

Ordered workflow modules should follow `1_<purpose>.py`, `2_<purpose>.py`, and so on as stabilization proceeds. Existing migration-era filenames may remain until wrappers and tests are complete.

## External runtime

Generated files do not belong in the checkout. The approved structure is:

```text
# Runtime artifacts live outside Git.
CapacityPlanningDigitalTwin/
  current.json
  artifacts/
    <run_id>/
      raw/sqlite/
        raw_demand.db
        raw_product.db
        raw_site.db
        raw_machine.db
        raw_test.db
        raw_yield.db
        raw_execution.db
      reference.duckdb
      mapping.duckdb
      bronze.duckdb
      silver.duckdb
      gold.duckdb
      serving.duckdb
      ml.duckdb
      manifest.json
      logs/
      models/
      reports/
```

Small pointer files select the current source, pipeline, ML, and compatible release. Applications use `release_current.json` when they need Serving and ML together.

The runtime root is selected by `CAPACITY_TWIN_HOME`; the Windows default is `%LOCALAPPDATA%\CapacityPlanningDigitalTwin`.

## Root guardrail

Do not reintroduce an `apps/` container or mixed legacy roots such as root-level `backend/`,
`frontend/`, or `config/`. Generated `data/`, `models/`, `logs`, Spark warehouses, reports,
notebooks, and caches must remain outside the repository.
