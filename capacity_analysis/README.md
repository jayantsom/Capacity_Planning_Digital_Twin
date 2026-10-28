# Capacity Analysis

Capacity Analysis is the tactical capacity and bottleneck application. It is served at
`/capacity-analysis/` by the combined local application.

## Views

- **Tactical Capacity** keeps Normal Capacity, Maximum Capacity, Actual Output, and
  Demonstrated Capacity distinct. It includes KPIs, monthly demand and supply, an
  exact capacity-loss bridge, site-test gaps, constrained resources, equipment need,
  and qualified alternatives.
- **Bottleneck Analysis** reports resource-hour constraints, severity, affected
  products, movement over time, qualified alternatives, and equipment investment need.

Actual Output is measured production. It is not capacity. Demonstrated Capacity is the
governed trailing measured-output formula published by the data pipeline.

## Data and readiness

The backend captures `release_current.json` once per request and opens only its pinned,
self-contained `serving.duckdb` in read-only mode. It does not fall back to mutable
aliases or query Gold, Silver, Reference, Mapping, Raw, or ML databases.

The app returns a clear not-ready state when the compatible release or any required
materialized Serving table is missing. Queries aggregate on the server and enforce the
point and row budgets in `config.yaml`.

## Filters

The server declares filter options with full labels and codes. Both views support site,
product, test type, Normal or Maximum capacity mode, No Retest or Type 1 or Type 2
retest, planning version, and monthly range.

## Run and test

Run the shared application:

```powershell
uv run capacity-twin
```

Run focused tests:

```powershell
uv run pytest capacity_analysis capacity_home/tests/test_routes.py
```

The application never writes to or promotes the active runtime.
