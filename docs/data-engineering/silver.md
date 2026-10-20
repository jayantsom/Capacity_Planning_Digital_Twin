# Silver Layer

Silver converts validated Raw-shaped records into conformed telecom manufacturing data. PySpark remains the existing transformation engine and runs locally for the one-server workstation target.

## Responsibilities

- Deterministically deduplicate rows already flagged in Bronze.
- Preserve invalid records in quarantine instead of silently dropping them.
- Conform products, sites, factories, dates, snapshots, routes, resources, and units.
- Reconcile execution with test-parameter and log facts.
- Keep parent BOM-dependent demand separate from independent direct, spare, and service demand.
- Apply effective-dated sourcing and route qualification.
- Assert key uniqueness and join cardinality before writes.
- Write `silver.duckdb` without changing `bronze.duckdb`.

Lag and rolling features used later by ML must be grouped by their declared series and shifted behind the target period. Snapshot and month keys must remain part of the grain wherever they affect identity.

## Execution

The implemented runner invokes Silver between Bronze and Gold:

```powershell
# Run all implemented medallion stages in order.
uv run capacity-pipeline
```

No row counts or execution times are promised. Validity is established by schema, key, date, quantity, quarantine, and reconciliation tests.

The transforms are under `data_operations/pipeline/pipeline/silver/`.
Candidate-file publication and rollback stay behind the Data Operations API.
