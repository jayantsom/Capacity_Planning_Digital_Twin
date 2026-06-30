# CapEx Monte Carlo Optimisation

> **File**: `src/ml/models/capex_montecarlo.py`
> **Output tables**: `gold_capex_mc_summary` (181 rows), `gold_capex_mc_scenarios` (543 rows)
> **Run time**: ~5s

---

## What problem does this solve?

> *"How many testers should a site purchase — given that demand, yield, and OEE are all uncertain?"*

Deterministic capacity math gives a single number. Monte Carlo answers: *"at what equipment quantity are you covered in 80% of plausible futures?"*

---

## Why Monte Carlo?

| Approach | Problem |
|---|---|
| Static capacity math | Single-point estimate; ignores uncertainty |
| Sensitivity analysis | Tests one variable at a time |
| **Monte Carlo** | Jointly samples all uncertain inputs; gives probability distribution over outcomes |

10,000 iterations per site × test_type (181 combos = 1.81M total simulations).

---

## What inputs are uncertain, and how are they sampled?

| Variable | Distribution | Parameters | Rationale |
|---|---|---|---|
| Demand | $\mathcal{N}(\mu, \mu \times CV)$ | μ = max demand per site; CV from history | Symmetric variation around forecast |
| OEE | $\text{Triangular}(\min, \text{mode}, \max)$ | From site OEE history ± 5% margin | Bounded; mode = most likely value |
| Yield | $\text{Beta}(\alpha, \beta)$ | Fit via method of moments | Naturally bounded [0,1] |

### Beta distribution fitting (method of moments)

$$\alpha = \mu \left(\frac{\mu(1-\mu)}{\sigma^2} - 1\right), \quad \beta = (1-\mu)\left(\frac{\mu(1-\mu)}{\sigma^2} - 1\right)$$

Minimum values clamped to 0.5 to avoid degenerate distributions.

---

## How does one simulation iteration work?

```
1. Sample demand_sim   ~ Normal(demand_mean, demand_mean × CV)  [clip ≥ 0]
2. Sample oee_sim      ~ Triangular(oee_low, oee_mode, oee_high) [clip 0.01–1]
3. step2_sim           = step1_base / oee_sim
4. step3_sim           = (shift_hrs × 3600 × (1−allowance) × productivity) / step2_sim
5. supply_per_tester   = step3_sim × (working_days × shifts_per_day)
6. equipment_needed    = ⌈demand_sim / supply_per_tester⌉
```

`step1_base` is the median Step 1 from `gold_gcm_base` for that site × test_type (pre-computed with median yield).

---

## What do P50 / P80 / P95 mean?

| Percentile | Meaning | Use case |
|---|---|---|
| P50 | 50% of simulations need ≤ this many testers | Optimistic; lower cost, higher risk |
| **P80** | 80% of simulations satisfied | **Recommended planning target** |
| P95 | 95% of simulations satisfied | Conservative; near-zero risk |

P80 is the standard industrial planning service level — analogous to safety stock at the 80th demand percentile in inventory management.

---

## How is CapEx computed?

```
delta_units_p80 = max(eq_needed_p80 − current_equipment_qty, 0)
capex_usd_p80   = delta_units_p80 × equipment_unit_cost_usd
```

**Equipment unit costs (USD)**:

| Test Type | Cost | Test Type | Cost |
|---|---|---|---|
| OTA | $850,000 | FCT | $95,000 |
| TRX | $620,000 | ICT | $110,000 |
| PIM | $480,000 | BIT | $85,000 |
| PAM | $720,000 | ALT | $160,000 |
| UC  | $200,000 | AT  | $130,000 |

---

## Results

| Metric | Value |
|---|---|
| Combos simulated | 181 |
| Iterations per combo | 10,000 |
| Combos needing investment (P80) | 27 |
| Total P80 CapEx recommendation | **$32,070,000** |
| Scenario rows (3 per combo) | 543 |

---

## Output schemas

### `gold_capex_mc_summary`

| Column | Description |
|---|---|
| `site_code`, `test_type` | Equipment identifier |
| `current_equipment_qty` | Existing tester count |
| `eq_needed_p50/p80/p95` | Percentile equipment quantities |
| `delta_units_p80` | Additional units needed at P80 |
| `capex_usd_p80` | USD investment at P80 |
| `equipment_unit_cost_usd` | Per-unit cost |
| `demand_mean` | Mean demand used in simulation |
| `n_simulations` | Always 10,000 |

### `gold_capex_mc_scenarios`

| Column | Description |
|---|---|
| `site_code`, `test_type` | Equipment identifier |
| `scenario` | `underinvest_p50` / `target_p80` / `overinvest_p95` |
| `equipment_qty` | Equipment quantity for this scenario |
| `probability_sufficient` | Fraction of simulations satisfied |
| `capex_usd` | Investment cost for this scenario |
