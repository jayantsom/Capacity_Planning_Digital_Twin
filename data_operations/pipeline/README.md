# Data Pipeline

Builds Bronze, Silver, Gold, and Serving in that order. Each layer is a separate
DuckDB file under
`<CAPACITY_TWIN_HOME>/artifacts/<run_id>/`. The pipeline validates a complete
candidate before atomically changing `<CAPACITY_TWIN_HOME>/current.json`.

Run a new candidate:

```powershell
# Build all four layers and promote only after every check passes.
uv run capacity-pipeline run
```

Retry and rollback:

```powershell
# A retry creates a new candidate linked to the failed run.
uv run capacity-pipeline retry <failed_run_id>

# Rollback changes only current.json after verifying prior checksums.
uv run capacity-pipeline rollback
```

`manifest.json` records the config hash, source/table counts, stage timings,
checksums, validation status, parent run, retry source, and promotion state.
Bronze preserves Raw rows and marks duplicate keys. Silver keeps rejected rows
in `slvr_quarantine`. Gold and Serving are never exposed from an incomplete run.

Settings are in `config.yaml`. Fast tests use temporary runtime directories:

```powershell
# Run the app-owned correctness and publication tests.
uv run pytest data_operations/pipeline/tests -q
```
