# Data Engineering Pipeline

The flow is Raw to Bronze to Silver to Gold to Serving. ML reads the compatible Serving release and publishes evaluated outputs separately. Reference and Mapping are governed source controls, not Raw transactions.

| Layer | Physical storage | Responsibility |
|---|---|---|
| Raw | Nine SQLite files | Synthetic source records, including declared noise |
| Reference | `reference.duckdb` | Canonical business entities and rules |
| Mapping | `mapping.duckdb` | Source-to-canonical identifiers and relationships |
| Bronze | `bronze.duckdb` | Structural validation, typing, identity, and noise flags |
| Silver | `silver.duckdb` | Deterministic cleaning, deduplication, conformance, and quarantine |
| Gold | `gold.duckdb` | Capacity equations, demand reconciliation, OEE, and analytics |
| Serving | `serving.duckdb` | Materialized application-facing tables |
| ML | `ml.duckdb` | Evaluated workflow outputs and model metadata |

Each step reads upstream files without modifying them. Candidates are immutable. Promotion changes a small pointer file. It never overwrites a promoted database.

## Run lifecycle

1. Compile Reference and Mapping, then estimate size.
2. Generate all nine Raw databases from one seed and catalog.
3. Write the source manifest and noise truth manifest.
4. Build Bronze, Silver, Gold, and Serving in order.
5. Validate schemas, checksums, business keys, dates, quantities, join cardinality, and capacity equations.
6. Build and validate ML outputs.
7. Promote one compatible release through `release_current.json`.
8. Retain previous releases for rollback.

Source manifests pin Reference and Mapping checksums. Pipeline and ML manifests pin their upstream run IDs. Health is READY only when the selected release exists and lineage agrees.

Pointer roles:

| Pointer | Selects |
|---|---|
| `source_current.json` | Source bundle |
| `current.json` | Pipeline run |
| `ml_current.json` | ML run |
| `release_current.json` | Compatible source, pipeline, and ML release |

## Commands

```powershell
# Generate inputs and run the implemented pipeline entry point.
uv run capacity-generate
uv run capacity-pipeline

# Publish the ML workflow outputs.
uv run capacity-ml
```

No fixed rows, runtimes, or table counts are documented because they vary by profile and have not been re-baselined against the approved telecom catalog.
