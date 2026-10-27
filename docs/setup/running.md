# Running the Project

Run commands from the repository root. Keep `CAPACITY_TWIN_HOME` outside the checkout.

```powershell
# Select the external runtime and execute workloads in order.
$env:CAPACITY_TWIN_HOME = "$env:LOCALAPPDATA\CapacityPlanningDigitalTwin"
uv run capacity-generate
uv run capacity-pipeline
uv run capacity-ml
```

The registered scripts resolve to:

- `capacity-generate` → `data_operations.generator.generators.run_all_generators:main`
- `capacity-pipeline` → `data_operations.pipeline.runner:main`
- `capacity-ml` → `decision_intelligence.ml.run_ml:main`
- `capacity-twin` → `capacity_home.main:main`

## Operations Assistant

Start Ollama only when local assistant features are needed:

```powershell
# Run the optional model service, then the shared local application.
ollama serve
uv run capacity-twin
```

The shared server binds to `127.0.0.1:8000` and serves Home, Operations Assistant,
Data Explorer, Decision Intelligence, and Data Operations from one process.

## Tests

```powershell
# Run app-owned tests and static checks.
uv run pytest -q
uv run ruff check capacity_home operations_assistant data_explorer data_operations decision_intelligence src
```

Do not use console logs or old documentation as proof of rows, runtimes, model scores, or publication success. Use the candidate run’s manifest and validation report.
