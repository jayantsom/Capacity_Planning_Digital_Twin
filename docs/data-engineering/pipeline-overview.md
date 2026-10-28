# Data Engineering Pipeline

The flow is Raw to Bronze to Silver to Gold to Serving. ML reads the compatible Serving release and publishes evaluated outputs separately. Reference and Mapping are governed source controls, not Raw transactions.

| Layer | Physical storage | Responsibility |
|---|---|---|
| Raw | Seven SQLite files, 18 tables | Synthetic source records, including declared noise |
| Reference | `reference.duckdb` | Canonical business entities and rules |
| Mapping | `mapping.duckdb` | Source-to-canonical identifiers and relationships |
| Bronze | `bronze.duckdb`, 18 tables | Structural validation, typing, identity, and noise flags |
| Silver | `silver.duckdb`, 22 tables | Deterministic cleaning, deduplication, conformance, and quarantine |
| Gold | `gold.duckdb`, 14 tables | Capacity equations, demand reconciliation, OEE, and analytics |
| Serving | `serving.duckdb`, 19 tables | Materialized application-facing tables |
| ML | `ml.duckdb`, 12 tables | Evaluated workflow outputs and model metadata |

Each step reads upstream files without modifying them. Candidates are immutable. Promotion changes a small pointer file. It never overwrites a promoted database.

## Run lifecycle

1. Compile Reference and Mapping, then estimate size.
2. Generate all seven Raw databases from one seed and catalog.
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

Row counts and runtimes vary by profile. The published schema is fixed at 18 Raw,
18 Bronze, 22 Silver, 14 Gold, 19 Serving, and 12 ML tables.
