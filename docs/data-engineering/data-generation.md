# Synthetic Data Generation

`data_operations/generator/` owns telecom catalogs, rules, generation, preflight
checks, noise, and Raw publication. Run it from the Data Operations dashboard or with:

```powershell
# Build one immutable source bundle.
uv run capacity-generate
```

## Scope

Erivon is the single fictional primary brand and uses `ERV_*` codes. Products cover telecom/networking parent systems and child PCB, RF, optical, power, and access modules. Sites, routes, volumes, capabilities, and performance are synthetic. Real EMS or equipment-vendor references do not imply affiliation or actual production assignments.

Dates come from the run configuration. The default actual cutoff is 2026-10-31. Historical actuals are stable across later planning versions, and each planning version sees actuals only through its own as-of date.

## Source bundle

Every run publishes nine Raw SQLite files plus `reference.duckdb` and `mapping.duckdb`:

- `raw_demand.db`
- `raw_product.db`
- `raw_site.db`
- `raw_machine.db`
- `raw_test.db`
- `raw_yield.db`
- `raw_execution.db`
- `raw_inventory.db`
- `raw_npi.db`
- `reference.duckdb`
- `mapping.duckdb`

The source bundle manifest records the shared run ID, schema versions, table counts, file checksums, and canonical bundle checksum. `source_current.json` is switched only after validation.

## Business contracts

Demand types are `DIRECT_CUSTOMER`, `SPARE`, `SERVICE`, and `BOM_DEPENDENT`. BOM-dependent child quantities and independent child demand remain distinct and reconcile to total child requirement.

Routes apply to every made child and every parent assembly. Effective-dated sourcing supports `MAKE`, `BUY_TESTED`, and `BUY_REQUIRES_INCOMING_TEST`.

Each route step declares exactly one behavior:

- `ALTERNATIVE_POOL`
- `SERIAL_STEP`
- `PAIRED_FIXTURE`
- `MULTI_DUT`
- `STANDALONE`
- `SHARED_POOL`
- `DEDICATED`

## Noise and validation

Raw data is intentionally noisy, not arbitrarily corrupt. Named rules cover duplicates, missing execution, null measurements, outliers, late records, stale dimensions, and controlled broken references.

Preflight must reject invalid dates, BOM cycles, missing routes, impossible sourcing, orphan resources, invalid pools, incompatible tester-fixture links, physical multi-DUT violations, nondeterministic keys, and projected profile overages. Publication is atomic only after schema, checksum, reconciliation, and validation checks pass.

The tracked source contracts and migration matrix define ownership, keys, grain, units, null policy, mapping policy, lineage, budgets, schema versions, and consumers.
