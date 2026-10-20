# Gold and Serving Layers

Gold applies the trusted capacity, OEE, demand, and snapshot contracts. Serving exposes stable read-only views to Capacity Assistant and Data Explorer.

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

Capacity is calculated at a declared site, product, route step/test, month, and snapshot grain. Aggregation to resource pools occurs before fleet comparison so supply is not duplicated by product fan-out.

## Publication

Gold reads `silver.duckdb`; Serving reads validated Gold and ML outputs. Both are candidate files until manifests confirm schemas, checksums, cardinality, demand conservation, resource conservation, capacity equations, and smoke queries. APIs open only the promoted `serving.duckdb` read-only.

```powershell
# Build the implemented Bronze, Silver, and Gold sequence.
uv run capacity-pipeline
```

Gold tables use `gold_*` names and read only the validated Silver candidate.
Serving views use `srv_vw_*` names and are published only after table, grain,
and smoke-query checks pass.
