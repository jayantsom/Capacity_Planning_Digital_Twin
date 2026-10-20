# Data Engineering Pipeline

The approved flow is Raw → Bronze → Silver → Gold → ML → Serving.

| Layer | Physical storage | Responsibility |
|---|---|---|
| Raw | Ten SQLite files | Synthetic source records, including declared noise |
| Bronze | `bronze.duckdb` | Structural validation, typing, identity, and noise flags |
| Silver | `silver.duckdb` | Deterministic cleaning, deduplication, conformance, and quarantine |
| Gold | `gold.duckdb` | Capacity equations, demand reconciliation, OEE, and analytics |
| ML | `ml.duckdb` | Evaluated workflow outputs and model metadata |
| Serving | `serving.duckdb` | Stable read-only views for Capacity Assistant and Data Explorer |

Each downstream step reads upstream files without modifying them. Candidate files are built and validated under one run directory. Promotion changes only `current.json`; it never overwrites a promoted database.

## Run lifecycle

1. Compile an immutable telecom catalog and estimate size.
2. Generate all Raw databases from one seed and catalog.
3. Write the Raw truth manifest and validation report.
4. Build Bronze, Silver, Gold, ML, and Serving candidates in order.
5. Validate schemas, checksums, business keys, dates, quantities, join cardinality, and capacity equations.
6. Mark errors as blocking; report expected noise separately.
7. Atomically promote the run pointer and retain the previous accepted run for rollback.

The current `capacity-pipeline` runner executes Bronze, Silver, and Gold in dependency order. Complete run-scoped physical separation and atomic pointer promotion remain stabilization targets and should not be described as proven until end-to-end tests pass.

## Commands

```powershell
# Generate inputs and run the implemented pipeline entry point.
uv run capacity-generate
uv run capacity-pipeline

# Publish the five existing ML workflow outputs.
uv run capacity-ml
```

No fixed rows, runtimes, or table counts are documented because they vary by profile and have not been re-baselined against the approved telecom catalog.
