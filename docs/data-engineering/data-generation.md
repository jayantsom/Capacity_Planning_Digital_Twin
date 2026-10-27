# Synthetic Data Generation

`data_operations/generator/` owns telecom catalogs, rules, generation, preflight
checks, noise, and Raw publication. Run it from the Data Operations dashboard or with:

```powershell
# Build the ten configured Raw SQLite databases.
uv run capacity-generate
```

## Scope

Erivon is the single fictional primary brand and uses `ERV_*` codes. Products cover telecom/networking parent systems and child PCB, RF, optical, power, and access modules. Sites, routes, volumes, capabilities, and performance are synthetic. Real EMS or equipment-vendor references do not imply affiliation or actual production assignments.

Actual and execution records span 2023-01-01 through 2026-10-31. Forecast records span 2026-11-01 through 2027-12-31. Historical actuals are stable across later planning versions, and each planning version sees actuals only through its own as-of date.

## Ten Raw databases

The app configuration declares:

- `raw_demand_forecast.db`
- `raw_product_master.db`
- `raw_target_test_time.db`
- `raw_target_yield.db`
- `raw_site_equip_inv.db`
- `raw_site_soft.db`
- `raw_machine_execution.db`
- `raw_machine_test_param.db`
- `raw_machine_logs.db`
- `raw_reference_data.db`

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

Raw data is intentionally noisy, not arbitrarily corrupt. Named rules cover duplicates, missing execution, null measurements, outliers, late records, stale dimensions, and controlled broken references. Stable event IDs link each injected defect to a private truth manifest and an expected Bronze/Silver disposition.

Preflight must reject invalid dates, BOM cycles, missing routes, impossible sourcing, orphan resources, invalid pools, incompatible tester-fixture links, physical multi-DUT violations, nondeterministic keys, and projected profile overages. Publication is atomic only after schema, checksum, reconciliation, and validation checks pass.

The configuration and contract tables verify much of this vocabulary. Full truth-manifest and atomic Raw publication behavior could not be confirmed across the current generator implementation.
