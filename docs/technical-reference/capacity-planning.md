# Capacity Planning Fundamentals

> This document covers all industrial engineering concepts, terminology, formulas, and worked examples underlying the digital twin's capacity math engine.

---

## Table of Contents

1. [What is Capacity Planning?](#1-what-is-capacity-planning)
2. [Key Terminology](#2-key-terminology)
3. [The Manufacturing Context](#3-the-manufacturing-context)
4. [Operational Parameters](#4-operational-parameters)
5. [The 5-Step Capacity Math Engine](#5-the-5-step-capacity-math-engine)
6. [Retest Models](#6-retest-models)
7. [Bottleneck Classification](#7-bottleneck-classification)
8. [Yield and Its Effect on Capacity](#8-yield-and-its-effect-on-capacity)
9. [OEE — Overall Equipment Effectiveness](#9-oee--overall-equipment-effectiveness)
10. [Worked Example: End-to-End Capacity Calculation](#10-worked-example-end-to-end-capacity-calculation)
11. [Demand vs Supply: Interpretation Guide](#11-demand-vs-supply-interpretation-guide)
12. [Planning Scenarios: Normal vs Maximum](#12-planning-scenarios-normal-vs-maximum)

---

## 1. What is Capacity Planning?

**Capacity planning** is the process of determining the production capacity needed to meet changing demand for a product or service. In semiconductor and telecom test equipment manufacturing, it answers the question:

> *"Given the demand for the next 12–18 months, do we have enough test equipment to test all units, and if not, where do we need to invest?"*

Capacity planning operates at two levels:

| Level | Question | Output |
|---|---|---|
| **Tactical** | Can we meet demand next month with current equipment? | Utilisation rate, gap quantity |
| **Strategic** | Do we need to buy new testers for the next planning cycle? | CapEx recommendation, investment units |

In this system, both levels are computed simultaneously — the gold layer produces monthly tactical views and the Monte Carlo model produces strategic CapEx recommendations.

---

## 2. Key Terminology

| Term | Definition |
|---|---|
| **Test Equipment / Tester** | A machine that validates whether a manufactured unit meets specification. Different test types require different tester hardware. |
| **Test Type** | The category of test being performed. Ten types exist: OTA, TRX, PIM, PAM, FCT, ICT, BIT, ALT, UC, AT. Each maps to different equipment and test times. |
| **DUT** | Device Under Test — the unit being tested (e.g. a radio module, antenna, circuit board). |
| **Cycle Time** | Total elapsed time from start to finish for one DUT on one tester, including handling and actual test. |
| **Handling Time** | Time spent loading/unloading the DUT — does not include actual test execution. Measured in seconds. |
| **Test Time** | Time the tester is actively running the test sequence on one DUT. Measured in seconds. |
| **Yield** | The fraction of DUTs that pass on the first test attempt. A yield of 0.85 means 85 out of 100 units pass first time. |
| **Retest** | A unit that fails the first test must be retested. Retests consume additional tester time, reducing effective capacity. |
| **Utilisation Rate** | The fraction of available tester time that is productively used. A rate of 0.80 means 80% of time is used for testing (20% is overhead, changeover, etc.). |
| **Allowance** | A planned deduction from available shift time to account for scheduled maintenance, breaks, and setup. Expressed as a fraction (e.g. 0.10 = 10%). |
| **Productivity** | The fraction of non-allowance time that results in productive output. Accounts for minor stoppages, quality issues, etc. (e.g. 0.95 = 95%). |
| **Shift** | One contiguous working period. This system uses `hours_per_shift_normal` (typically 8 hours). |
| **Capacity (Supply)** | The maximum number of DUTs a tester fleet can process in a given time period, given all operational parameters. |
| **Demand** | The number of DUTs that need to be tested in a given period, derived from production plans. |
| **Gap** | Supply minus Demand. Positive gap = excess capacity. Negative gap = bottleneck (insufficient capacity). |
| **Gap %** | `(Supply − Demand) / Demand × 100`. The primary metric for assessing capacity adequacy. |
| **Bottleneck** | A constraint where demand exceeds supply, forcing production delays or requiring overtime/investment. |
| **NPI** | New Product Introduction — a product newly entering the production line. NPI products have shorter demand history, fewer qualified test sites, and lower initial yield. |
| **Snapshot** | A point-in-time capture of the production plan. Two snapshots exist: `snap-2023-01-planning-cycle` and `snap-2024-01-planning-cycle`. |
| **GCM** | Global Capacity Model — the master dataset joining product, equipment, and operational parameters. |
| **OEE** | Overall Equipment Effectiveness — a composite metric of availability, performance, and quality. |
| **Planning Horizon** | The forward time window for which capacity is planned. This system covers Jul 2026 – Dec 2027 (18 months). |
| **CapEx** | Capital Expenditure — money spent to purchase new test equipment. |
| **P50 / P80 / P95** | Monte Carlo percentile outputs. P80 = equipment quantity needed to satisfy demand in 80% of simulated scenarios. |

---

## 3. The Manufacturing Context

This digital twin models a **telecom test equipment manufacturing** environment with the following characteristics:

- **22 manufacturing sites** across 18 countries, operated by 6 suppliers (Ericsson, Jabil, Flex, Infineon, Sanmina, Luxshare)
- **35 products** across 5 platforms and 17 product families
- **10 test types** covering RF, functional, in-circuit, burn-in, and acceptance testing
- **Time range**: January 2023 actuals through December 2027 (forecast)

Each product must pass through one or more test types before shipping. Each test type requires specific equipment. The capacity question is: for each site × test type × month combination, does available equipment supply meet demand?

---

## 4. Operational Parameters

### Shift Structure

```
Working Days per Month  ×  Shifts per Day  ×  Hours per Shift
        22            ×        3           ×        8 hrs
= 528 total hours per tester per month (before allowance/productivity)
```

**Normal mode** uses standard shift parameters. **Maximum mode** uses extended shifts (more shifts per day, sometimes more working days) to model surge capacity.

### Allowance and Productivity

| Parameter | Typical Value | What it covers |
|---|---|---|
| `allowance_pct` | 0.10 (10%) | Planned maintenance windows, shift changeover, scheduled breaks |
| `productivity_pct` | 0.95 (95%) | Minor stoppages, material delays, process variation |

These are applied multiplicatively in Step 3:

```
Effective hours = shift_hours × 3600 × (1 − allowance) × productivity
```

### Test Type Reference

| Code | Full Name | Category | Typical Test Time | Equipment Cost |
|---|---|---|---|---|
| OTA | Over-the-Air | RF | High | $850K |
| TRX | Transceiver | RF | Medium | $620K |
| PIM | Passive Intermodulation | RF | Medium | $480K |
| PAM | Power Amplifier Module | RF | High | $720K |
| FCT | Functional Circuit Test | Functional | Low | $95K |
| ICT | In-Circuit Test | Functional | Low | $110K |
| BIT | Built-In Test | Functional | Low | $85K |
| ALT | Accelerated Life Test | Reliability | Very High | $160K |
| UC | Utilisation Check | Acceptance | Medium | $200K |
| AT | Acceptance Test | Acceptance | Low | $130K |

---

## 5. The 5-Step Capacity Math Engine

The capacity engine converts raw operational parameters into a single comparable metric: **units of demand that one tester can satisfy per month**. All five steps are computed in `src/pipeline/gold/capacity_math.py`.

---

### Step 1 — Adjusted Test Time per Unit (seconds)

**Purpose**: Compute the actual average time a tester spends per DUT, accounting for the fact that some units will fail and require retesting.

$$\text{Step 1} = (t_{handle} + t_{test}) \times \left[1 + (1 - Y) \times R \times X\right]$$

Where:
- $t_{handle}$ = handling time per unit (seconds)
- $t_{test}$ = test time per unit (seconds)
- $Y$ = first-pass yield (fraction, 0–1)
- $R$ = retest times (model-dependent, see §6)
- $X$ = test_x_parameter (model-dependent, see §6)

**Interpretation**: If yield is 100% ($Y = 1$), the bracket becomes $[1 + 0] = 1$, so Step 1 = base cycle time. If yield is 85%, some units need retesting, so the effective time per unit is higher than the base cycle time.

---

### Step 2 — Total Test Time Accounting for Utilisation (seconds)

**Purpose**: Account for the fact that testers are not 100% productive — some time is lost to overhead not captured in handling time.

$$\text{Step 2} = \frac{\text{Step 1}}{U}$$

Where:
- $U$ = utilisation rate (fraction, e.g. 0.85)

**Interpretation**: If utilisation is 85%, the tester must be "allocated" $\frac{1}{0.85}$ seconds of calendar time for every second of productive test time.

---

### Step 3 — Units per Tester per Shift (units/shift)  ← **Adjusted Formula**

**Purpose**: Convert from seconds-per-unit to units-per-tester-per-month, applying allowance and productivity.

$$\text{Step 3} = \frac{H \times 3600 \times (1 - A) \times P}{\text{Step 2}}$$

Where:
- $H$ = hours per shift (e.g. 8)
- $A$ = allowance fraction (e.g. 0.10)
- $P$ = productivity fraction (e.g. 0.95)
- $3600$ = seconds per hour

> **Why "Adjusted"?** The authoritative formula includes both allowance and productivity factors applied to available shift time. An earlier non-adjusted formula omitted productivity. The adjusted formula is the locked, authoritative implementation.

**Interpretation**: This gives the number of DUTs one tester can process in one shift, after all practical deductions.

---

### Step 4 — Monthly Shifts per Tester

**Purpose**: Convert from per-shift to per-month by counting the total number of shifts worked in a month.

$$\text{Step 4} = D \times S$$

Where:
- $D$ = working days per month (e.g. 22)
- $S$ = shifts per day (e.g. 3)

**Example**: 22 working days × 3 shifts/day = 66 shifts per month.

---

### Step 5 — Capacity Need and Supply

**Purpose**: Determine how many testers are needed to meet demand, and whether current inventory is sufficient.

**Units needed** (fractional):

$$\text{Step 5 (Need)} = \frac{\text{Demand}}{\text{Step 3} \times \text{Step 4}}$$

**Supply** (units that can be tested by existing fleet):

$$\text{Supply} = \text{equip\_qty} \times \text{Step 3} \times \text{Step 4}$$

**Capacity Gap %**:

$$\text{Gap \%} = \frac{\text{Supply} - \text{Demand}}{\text{Demand}} \times 100$$

**Interpretation**:
- Gap% = +20% → 20% excess capacity (comfortable)
- Gap% = −10% → demand exceeds supply by 10% (HIGH bottleneck)
- Gap% = −20% → demand exceeds supply by 20% (CRITICAL bottleneck)

---

## 6. Retest Models

Two retest models are implemented, selected by the `retest_type` column in GCM data.

### Type 1 — Fixed Retest Parameters

Used when retest behaviour is known and constant regardless of yield variation.

$$R = 2.0, \quad X = 0.75$$

The factor $R \times X = 1.5$ represents: on average, a failed unit requires 1.5 additional test-time equivalents.

### Type 2 — Yield-Derived Retest Parameters

Used when retest rates are derived from the yield structure of the product.

$$R = \frac{1 - Y_1 + Y_2}{Y_2}, \quad X = \text{retest\_quote}$$

Where:
- $Y_1$ = first-pass yield (`yield_retest_1`)
- $Y_2$ = yield at second attempt (`yield_retest_2_plus`)
- `retest_quote` = the quoted retest fraction from the equipment specification

**Interpretation**: Type 2 is more accurate for products where retest yield is measured separately from first-pass yield.

---

## 7. Bottleneck Classification

Every site × test_type × month combination is assigned a severity tier based on Gap%:

| Severity | Gap % Threshold | Operational Meaning |
|---|---|---|
| **CRITICAL** | Gap% < −15% | Demand exceeds supply by more than 15%. Cannot be absorbed by overtime. Immediate investment required. |
| **HIGH** | −15% ≤ Gap% < −8% | Significant shortfall. Risk of production delays without mitigation. |
| **MEDIUM** | −8% ≤ Gap% < −3% | Moderate shortfall. May be manageable with overtime or scheduling optimisation. |
| **LOW** | −3% ≤ Gap% < 0% | Minor shortfall. Likely absorbable in practice. |
| **BALANCED** | 0% ≤ Gap% ≤ +5% | Supply closely matches demand. Optimal operating condition. |
| **EXCESS** | Gap% > +5% | Supply significantly exceeds demand. Equipment may be underutilised. |

**Observed distribution in synthetic data**: EXCESS 82%, CRITICAL 13%, HIGH 2%, MEDIUM 1%, BALANCED 1%, LOW 1%. This reflects intentional over-provisioning in the synthetic data generation to model a realistic over-invested manufacturing environment.

---

## 8. Yield and Its Effect on Capacity

Yield is the single most impactful parameter in the capacity math. A 10-percentage-point drop in yield (e.g. from 90% to 80%) does not reduce capacity by 10% — the effect is amplified through the retest factor.

**Intuition**: Lower yield → more units fail → more retests → each tester spends more time per DUT → fewer DUTs can be processed per month → effective supply drops.

**NPI yield effect**: New Product Introduction products start with yield 12% lower than the steady-state target. This means NPI products require significantly more tester capacity per unit during the ramp period, which is why demand forecasting uses Croston's method (designed for intermittent/lumpy demand) for NPI products.

**ML yield feedback**: The yield prediction model (Priority 2) predicts yield per product × site × test_type × month. These predictions replace the static `target_yield` values in the capacity math, producing `gold_cap_ml_adjusted` — a capacity view that reflects expected future yield rather than historical averages.

---

## 9. OEE — Overall Equipment Effectiveness

OEE is a composite measure of how well a tester fleet is being used, combining three factors:

$$\text{OEE} = \text{Availability} \times \text{Performance} \times \text{Quality}$$

| Component | Definition | Example |
|---|---|---|
| **Availability** | Actual uptime / Planned uptime | Equipment down 2hr in 8hr shift → 75% |
| **Performance** | Actual output rate / Target rate | Running at 90% of rated speed → 90% |
| **Quality** | Good units / Total units produced | 95% pass rate → 95% |

**Example**: $0.85 \times 0.90 \times 0.95 = 0.726$ → OEE of 72.6%

In this dataset, OEE ranges from **0.8077 to 0.9767** (mean 0.913). This narrow, high range is realistic for well-maintained semiconductor test equipment.

OEE is used in:
1. `gold_oee_metrics` — monthly OEE per site × test type
2. Predictive maintenance (Priority 3) — OEE < 0.88 within 3 months = failure label
3. OEE anomaly detection (Priority 4) — Isolation Forest on OEE time series

---

## 10. Worked Example: End-to-End Capacity Calculation

**Scenario**: OTA tester at site SG01, January 2024, normal capacity mode.

**Given parameters**:

| Parameter | Value |
|---|---|
| `handling_time_sec` | 45 seconds |
| `target_test_time_sec` | 180 seconds |
| `target_yield` (Y) | 0.87 (87%) |
| `retest_type` | Type 1 |
| `retest_times` (R) | 2.0 |
| `test_x_param` (X) | 0.75 |
| `utilization_rate` (U) | 0.82 |
| `hours_per_shift_normal` (H) | 8 |
| `allowance_pct` (A) | 0.10 |
| `productivity_pct` (P) | 0.95 |
| `working_days_normal` (D) | 22 |
| `shifts_per_day_normal` (S) | 3 |
| `equip_qty_available` | 12 testers |
| `effective_demand_qty` | 45,000 units |

---

**Step 1** — Adjusted test time per unit:

$$\text{Step 1} = (45 + 180) \times [1 + (1 - 0.87) \times 2.0 \times 0.75]$$

$$= 225 \times [1 + 0.13 \times 1.5]$$

$$= 225 \times [1 + 0.195]$$

$$= 225 \times 1.195 = 268.875 \text{ seconds/unit}$$

**Step 2** — Adjusted for utilisation:

$$\text{Step 2} = \frac{268.875}{0.82} = 327.896 \text{ seconds/unit}$$

**Step 3** — Units per tester per shift (adjusted):

$$\text{Step 3} = \frac{8 \times 3600 \times (1 - 0.10) \times 0.95}{327.896}$$

$$= \frac{28800 \times 0.90 \times 0.95}{327.896}$$

$$= \frac{24,624}{327.896} = 75.098 \text{ units/tester/shift}$$

**Step 4** — Monthly shifts per tester:

$$\text{Step 4} = 22 \times 3 = 66 \text{ shifts/month}$$

**Step 5** — Supply and Gap:

$$\text{Supply} = 12 \times 75.098 \times 66 = 59,477.6 \text{ units/month}$$

$$\text{Gap\%} = \frac{59,477.6 - 45,000}{45,000} \times 100 = +32.2\%$$

$$\text{Bottleneck Severity} = \textbf{EXCESS}$$

**Interpretation**: The 12 OTA testers at SG01 can handle 59,477 units but only 45,000 are demanded — 32.2% excess capacity. This site is over-provisioned for OTA testing in January 2024.

---

## 11. Demand vs Supply: Interpretation Guide

| Gap% | Severity | Action |
|---|---|---|
| < −15% | CRITICAL | Escalate immediately. Evaluate emergency procurement or demand reallocation to other sites. |
| −8% to −15% | HIGH | Plan investment in next budget cycle. Evaluate overtime or subcontracting. |
| −3% to −8% | MEDIUM | Monitor closely. Optimise scheduling. |
| 0% to −3% | LOW | Within operational tolerance. No immediate action. |
| 0% to +5% | BALANCED | Optimal. Minor scheduling optimisation opportunity. |
| > +5% | EXCESS | Consider equipment redeployment or demand reallocation from constrained sites. |

---

## 12. Planning Scenarios: Normal vs Maximum

Two capacity modes are computed for every combination:

| Mode | Description | When Used |
|---|---|---|
| **Normal** | Standard shift structure (`working_days_normal`, `shifts_per_day_normal`, `hours_per_shift_normal`) | Baseline planning |
| **Maximum** | Extended shift structure (`working_days_max`, `shifts_per_day_max`, `hours_per_shift_max`) | Surge capacity, risk mitigation |

The difference between Normal and Maximum capacity represents the **flexibility buffer** — how much additional throughput can be unlocked without buying new equipment.

$$\text{Flexibility\%} = \frac{\text{Supply}_{max} - \text{Supply}_{normal}}{\text{Supply}_{normal}} \times 100$$

A flexibility of 25% means the site can increase throughput by 25% by running maximum shifts before requiring capital investment.
