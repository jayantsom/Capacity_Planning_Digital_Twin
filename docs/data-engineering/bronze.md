# Bronze Layer

Bronze is the 18-table structural ingestion boundary between seven noisy Raw SQLite
sources and conformed data.

## Required behavior

- Read each configured source explicitly.
- Preserve stable source and event identity.
- Validate required columns, types, natural keys, units, and date bounds.
- Flag declared Raw duplicates and defects instead of silently losing evidence.
- Distinguish expected noise from unexpected corruption.
- Keep rejected records queryable through an explicit validation or quarantine path.
- Build `bronze.duckdb` as a candidate and validate it before publication.
- Never modify Raw databases.

Bronze does not repair business meaning. Deduplication, hierarchy reconciliation, route conformance, and forward-fill decisions belong downstream.

## Verification

Use app-owned tests rather than expected row counts:

```powershell
# Run the tests owned by the Pipeline module.
uv run pytest data_operations/pipeline/tests -q
```

Acceptance requires deterministic business keys, no accidental duplicate aggregation, preserved `is_valid` and `invalid_reason` states, valid empty schemas, and repeatable checksums for identical input.

Bronze ingestion lives under `data_operations/pipeline/pipeline/bronze/`.
Separate run-scoped publication and noise-manifest reconciliation are checked
through the Pipeline module's validations.
