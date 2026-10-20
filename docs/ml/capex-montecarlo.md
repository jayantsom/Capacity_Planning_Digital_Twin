# CapEx Monte Carlo Simulation

**Implementation:** `decision_intelligence/ml/models/capex_montecarlo.py`

This workflow samples demand, yield, OEE, and capacity assumptions to estimate equipment quantities at selected percentiles. It is simulation, not mathematical optimization, and its output is not an investment recommendation.

## Requirements

- Use deterministic seeds with independent random streams per site/resource combination.
- Actually sample configured yield uncertainty.
- Apply the same units and capacity equations as Gold.
- Respect route behavior, pooled resources, tester-fixture compatibility, and multi-DUT throughput.
- Publish assumptions, distribution parameters, iterations, seed, scenario percentile, current quantity, simulated need, and synthetic unit cost.
- Keep synthetic cost and capability assumptions clearly labeled.
- Return `not_evaluable` when an input distribution cannot be estimated.

P50, P80, and P95 describe simulated equipment-need percentiles, not guaranteed service levels. No iteration count, dollar total, runtime, or preferred percentile is asserted as a validated business result.
