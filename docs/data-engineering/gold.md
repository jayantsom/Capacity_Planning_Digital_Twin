# Gold and Serving Layers

Gold applies the trusted capacity, OEE, demand, and planning version contracts in
14 tables. Serving publishes 19 materialized read-only tables for the applications
and Yukti.

## Capacity principles

- Ratios remain fractions internally and become percentages only at presentation.
- OEE is availability × performance × quality.
- Serial steps receive full required demand once.
- Alternative resources are pooled once.
- Shared-product demand is aggregated against one shared fleet.
- Paired fixtures are constrained by compatible tester, fixture, handler, and licence availability.
- Standalone active fixtures are not paired again.
- Multi-DUT throughput uses the smallest physical/licensed constraint plus cycle time, OEE, changeover, and parallel efficiency.
- Dedicated resources serve only qualified products.
- Normal and maximum scenarios use explicit calendar and shift assumptions.

Capacity is calculated at a declared site, product, route step/test, month, and planning version grain. Aggregation to resource pools occurs before fleet comparison so supply is not duplicated by product fan-out.

## Operational time grains

Daily execution, test-parameter, and log facts also publish honest ISO-week and
calendar-month aggregates. Quantities are summed, yield is recomputed from passed
and tested quantities, weighted values keep their documented weights, and OEE
components are recomputed from period numerators and denominators. Monthly
planning, capacity, forecast, and ML values are never relabelled or divided into
invented weeks.

The operational tables expose period boundaries, source coverage, partial-period
status, and pipeline lineage. Decision Intelligence keeps monthly ML predictions
separate from its weekly/monthly operational panels.

## Publication

Gold reads `silver.duckdb`; Serving reads validated Gold and ML outputs. Both are candidate files until manifests confirm schemas, checksums, cardinality, demand conservation, resource conservation, capacity equations, and smoke queries. APIs open only the promoted `serving.duckdb` read-only.

```powershell
# Build the implemented Bronze, Silver, and Gold sequence.
uv run capacity-pipeline
```

Gold tables use `gold_*` names and read only the validated Silver candidate.
Serving views use `srv_vw_*` names and are published only after table, grain,
and smoke-query checks pass.
