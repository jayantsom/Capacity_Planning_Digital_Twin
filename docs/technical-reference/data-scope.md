# Data Scope

> Complete reference for the synthetic dataset dimensions, ranges, and identifiers.

---

## Dimensions at a glance

| Dimension | Count | Range / Values |
|---|---|---|
| Sites | 22 | 18 countries, 6 suppliers |
| Products | 35 | 5 platforms, 17 families |
| Test types | 10 | OTA/TRX/PIM/PAM/FCT/ICT/BIT/ALT/UC/AT |
| Months | 60 | Jan 2023 – Dec 2027 |
| Snapshots | 2 | `snap-2023-01-planning-cycle`, `snap-2024-01-planning-cycle` |
| NPI products | 5–7 | 2–3 qualified sites, 12-month ramp |

---

## Sites

| Supplier | Sites | Region |
|---|---|---|
| Ericsson | 4 | EMEA / APAC |
| Jabil | 4 | APAC / AMER |
| Flex | 4 | APAC / AMER |
| Infineon | 4 | EMEA |
| Sanmina | 3 | AMER |
| Luxshare | 3 | APAC |

Site code format: `{COUNTRY_CODE}{NN}` e.g. `SG01`, `DE03`, `US02`.
Region distribution: APAC 10, EMEA 8, AMER 4.

---

## Test types

| Code | Category | RF chamber | Relative test time | Unit cost |
|---|---|---|---|---|
| OTA | RF | ✅ | High | $850K |
| TRX | RF | ✅ | Medium | $620K |
| PIM | RF | ✅ | Medium | $480K |
| PAM | RF | ✅ | High | $720K |
| FCT | Functional | ❌ | Low | $95K |
| ICT | Functional | ❌ | Low | $110K |
| BIT | Functional | ❌ | Low | $85K |
| ALT | Reliability | ❌ | Very high | $160K |
| UC | Acceptance | ❌ | Medium | $200K |
| AT | Acceptance | ❌ | Low | $130K |

---

## Time ranges

| Period | month_key range | `is_actual` | Description |
|---|---|---|---|
| Actuals | 202301 – 202606 | 1 | Historical recorded values |
| Forecast | 202607 – 202712 | 0 | Planning horizon |

Planning horizon = 18 months from Jul 2026.

---

## Snapshots

| Snapshot ID | Represents | Key difference |
|---|---|---|
| `snap-2023-01-planning-cycle` | Jan 2023 planning cycle | Baseline; 2023 is entirely forecast |
| `snap-2024-01-planning-cycle` | Jan 2024 planning cycle | 2023 actuals incorporated; revised 2024+ forecasts |

Snapshot comparison drives `gold_forecast_accuracy` and `srv_vw_forecast_accuracy`.

---

## Key data ranges (verified from DuckDB)

| Metric | Min | Max | Mean |
|---|---|---|---|
| `target_yield` | 0.72 | 0.97 | ~0.87 |
| `oee_pct` | 0.8077 | 0.9767 | 0.913 |
| `utilization_pct` (gold_cap_normal) | < 0.1 | > 1.3 | ~0.7 |
| `gap_pct` | < −30% | > +80% | positive |

---

## Bottleneck distribution (gold_bottleneck)

| Severity | Share |
|---|---|
| EXCESS | 82% |
| CRITICAL | 13% |
| HIGH | 2% |
| MEDIUM | 1% |
| BALANCED | 1% |
| LOW | 1% |

EXCESS-heavy distribution reflects intentional equipment over-provisioning in generation logic, modelling a realistic over-invested manufacturing environment.
