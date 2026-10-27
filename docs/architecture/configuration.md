# Configuration

Configuration is app-owned and validated before startup.

| File | Owns |
|---|---|
| `capacity_home/config.yaml` | Local launcher server and allowed origins |
| `operations_assistant/config.yaml` | Local server, CORS origins, Ollama, model, streaming, and tool limits |
| `data_explorer/config.yaml` | Explorer route and query limits |
| `data_operations/config.yaml` | Dashboard origins, job policy, and Small/Medium/Full mappings |
| `data_operations/generator/config.yaml` | Erivon brand, dates, noise, budgets, and Raw filenames |
| `data_operations/pipeline/config.yaml` | Database filenames, Spark settings, and capacity thresholds |
| `decision_intelligence/config.yaml` | Evaluation, dashboards, jobs, and ML publication |
| `src/capacity_twin_core/config.yaml` | Runtime-root and logging defaults shared by apps |

Configuration precedence is app defaults, app `config.yaml`, environment variables, then explicit CLI options. Secrets must not be committed to YAML.

## Runtime root

`CAPACITY_TWIN_HOME` selects the external runtime directory. If it is unset on Windows,
Capacity Twin Core resolves `%LOCALAPPDATA%\CapacityPlanningDigitalTwin`.

```powershell
# Keep all generated artifacts outside the repository.
$env:CAPACITY_TWIN_HOME = "D:\CapacityTwinRuntime"
uv run capacity-generate
```

## Generator dates

- Actual/execution start: 2023-01-01
- Actual/execution cutoff: 2026-10-31
- Forecast start: 2026-11-01
- Forecast end: 2027-12-31
- Configured planning versions: 2025-10-31 and 2026-10-31

Volume changes density, not these contractual boundaries. The `local_16gb` limits are preflight gates, not claims that a measured run achieved those limits.

## Safety defaults

Operations Assistant binds to `127.0.0.1:8000`, allows only configured localhost origins, and uses `llama3.1:8b`. Data Explorer enforces default and maximum query limits. External binding requires an explicit future unsafe-development option because authentication is outside the local-only scope.
