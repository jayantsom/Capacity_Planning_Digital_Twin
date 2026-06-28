"""
Priority 5 — Monte Carlo CapEx Optimization
=============================================
10,000 simulations per site×test_type using real gcm_base column names.
Uncertainty: Demand (Normal), Yield (Beta), OEE (Triangular).
Output: P50/P80/P95 equipment needs + USD CapEx recommendation.

Output tables:
  gold_capex_mc_summary    — P50/P80/P95 per site×test_type
  gold_capex_mc_scenarios  — underinvest / target / overinvest breakdown
"""

import warnings
from typing import NamedTuple

import numpy as np
import pandas as pd

from src.utils.logger import logger as log
from src.utils.ml_utils import (
    get_conn,
    load_feature_store,
    load_table,
    upsert_table,
)

warnings.filterwarnings("ignore")

N_SIMULATIONS = 10_000
RANDOM_SEED   = 42
PERCENTILES   = [50, 80, 95]

EQUIPMENT_COST_BY_TEST_TYPE = {
    "OTA": 850_000, "TRX": 620_000, "PIM": 480_000, "PAM": 720_000,
    "FCT": 95_000,  "ICT": 110_000, "BIT": 85_000,  "ALT": 160_000,
    "UC":  200_000, "AT":  130_000,
}
DEFAULT_EQUIPMENT_COST = 300_000
DEMAND_CV_DEFAULT      = 0.15
OEE_MARGIN             = 0.05


class SimInputs(NamedTuple):
    demand_mean:    float
    demand_cv:      float
    yield_alpha:    float
    yield_beta:     float
    oee_low:        float
    oee_mode:       float
    oee_high:       float
    step1_base:     float
    shifts_per_day: float
    working_days:   float
    shift_hours:    float
    allowance:      float
    productivity:   float


def _fit_beta(values: np.ndarray):
    mu  = values.mean()
    var = values.var() + 1e-8
    c   = mu * (1 - mu) / var - 1
    return max(mu * c, 0.5), max((1 - mu) * c, 0.5)


def estimate_demand_uncertainty(fs: pd.DataFrame) -> pd.DataFrame:
    s = (fs.groupby(["product_number", "site_code"])["demand_qty"]
           .agg(["mean", "std"]).reset_index()
           .rename(columns={"mean": "demand_mean", "std": "demand_std",
                            "product_number": "product_id", "site_code": "site_id"}))
    s["demand_cv"] = (s["demand_std"] / s["demand_mean"].replace(0, np.nan)).fillna(DEMAND_CV_DEFAULT)
    return s


def estimate_yield_params(fs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for tt, grp in fs.groupby("test_type"):
        y = grp["target_yield"].dropna().clip(0.01, 0.999).values
        if len(y) < 5:
            rows.append({"test_type": tt, "yield_alpha": 5.0, "yield_beta": 1.0})
        else:
            a, b = _fit_beta(y)
            rows.append({"test_type": tt, "yield_alpha": a, "yield_beta": b})
    return pd.DataFrame(rows)


def estimate_oee_params(oee_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for site, grp in oee_df.groupby("site_code"):
        oee = grp["oee_pct"].dropna().clip(0.01, 1.0)
        if len(oee) == 0:
            rows.append({"site_code": site, "oee_low": 0.65, "oee_mode": 0.80, "oee_high": 0.95})
        else:
            mode = float(oee.mode().iloc[0])
            rows.append({"site_code": site,
                         "oee_low":  max(float(oee.min()) - OEE_MARGIN, 0.01),
                         "oee_mode": mode,
                         "oee_high": min(float(oee.max()) + OEE_MARGIN, 1.0)})
    return pd.DataFrame(rows)


def simulate_equipment_needed(inputs: SimInputs, n: int = N_SIMULATIONS) -> np.ndarray:
    rng = np.random.default_rng(RANDOM_SEED)

    demand_sim = rng.normal(inputs.demand_mean,
                            inputs.demand_mean * inputs.demand_cv, n).clip(0)
    oee_sim    = rng.triangular(inputs.oee_low, inputs.oee_mode,
                                inputs.oee_high, n).clip(0.01, 1.0)

    step2_sim = inputs.step1_base / oee_sim
    step3_sim = (inputs.shift_hours * 3600
                 * (1 - inputs.allowance)
                 * inputs.productivity) / step2_sim
    step4     = inputs.working_days * inputs.shifts_per_day

    supply_per_unit  = step3_sim * step4
    equipment_needed = np.ceil(demand_sim / supply_per_unit.clip(1e-6))
    return equipment_needed.clip(0)


def run_capex_montecarlo() -> dict:
    conn = get_conn()
    log.info("Loading gold_gcm_base and feature store...")
    gcm = load_table(conn, "gold_gcm_base")
    fs  = load_table(conn, "gold_ml_feature_store")   # raw names for uncertainty estimation
    oee = load_table(conn, "gold_oee_metrics")

    log.info("Estimating uncertainty distributions...")
    demand_params = estimate_demand_uncertainty(fs)
    yield_params  = estimate_yield_params(fs)
    oee_params    = estimate_oee_params(oee)

    # Representative row per site×test_type (median of gcm actuals)
    base = (
        gcm.groupby(["site_code", "test_type"])
        .agg(
            handling_time_sec       =("handling_time_sec",    "median"),
            target_test_time_sec    =("target_test_time_sec", "median"),
            utilization_rate        =("utilization_rate",     "median"),
            shifts_per_day          =("shifts_per_day_normal","median"),
            working_days            =("working_days_normal",  "median"),
            shift_hours             =("hours_per_shift_normal","median"),
            allowance               =("allowance_pct",        "median"),
            productivity            =("productivity_pct",     "median"),
            equip_qty_current       =("equip_qty_available",  "median"),
        )
        .reset_index()
    )

    # Compute baseline step1 (Type1: retest_times=2, test_x_param=0.75, median yield)
    gcm_yield = gcm.groupby(["site_code", "test_type"])["target_yield"].median().reset_index()
    base = base.merge(gcm_yield, on=["site_code", "test_type"], how="left")
    base["step1_base"] = (
        (base["handling_time_sec"] + base["target_test_time_sec"])
        * (1 + (1 - base["target_yield"].fillna(0.85)) * 2.0 * 0.75)
    )

    # Merge uncertainty params
    base = (base
            .merge(oee_params,  on="site_code", how="left")
            .merge(yield_params, on="test_type", how="left"))

    # Max demand per site (conservative)
    max_demand = (demand_params.groupby("site_id")
                  .agg(demand_mean=("demand_mean", "max"),
                       demand_cv=("demand_cv", "mean"))
                  .reset_index()
                  .rename(columns={"site_id": "site_code"}))
    base = base.merge(max_demand, on="site_code", how="left")

    base = base.fillna({
        "demand_mean": 500, "demand_cv": DEMAND_CV_DEFAULT,
        "yield_alpha": 5.0, "yield_beta": 1.0,
        "oee_low": 0.65,   "oee_mode": 0.80, "oee_high": 0.95,
        "allowance": 0.10,  "productivity": 0.95,
    })

    log.info(f"  Running {N_SIMULATIONS:,} simulations for {len(base):,} site×test_type combos...")

    mc_rows, scenario_rows = [], []

    for _, row in base.iterrows():
        inputs = SimInputs(
            demand_mean    = float(row["demand_mean"]),
            demand_cv      = float(row["demand_cv"]),
            yield_alpha    = float(row["yield_alpha"]),
            yield_beta     = float(row["yield_beta"]),
            oee_low        = float(row["oee_low"]),
            oee_mode       = float(row["oee_mode"]),
            oee_high       = float(row["oee_high"]),
            step1_base     = float(row["step1_base"]),
            shifts_per_day = float(row["shifts_per_day"]),
            working_days   = float(row["working_days"]),
            shift_hours    = float(row["shift_hours"]),
            allowance      = float(row["allowance"]),
            productivity   = float(row["productivity"]),
        )
        eq_needed = simulate_equipment_needed(inputs)

        eq_cost     = EQUIPMENT_COST_BY_TEST_TYPE.get(str(row["test_type"]), DEFAULT_EQUIPMENT_COST)
        current_qty = float(row["equip_qty_current"])
        p50, p80, p95 = np.percentile(eq_needed, PERCENTILES)
        delta_p80   = max(p80 - current_qty, 0)

        mc_rows.append({
            "site_code":             row["site_code"],
            "test_type":             row["test_type"],
            "current_equipment_qty": round(current_qty),
            "eq_needed_p50":         round(p50, 1),
            "eq_needed_p80":         round(p80, 1),
            "eq_needed_p95":         round(p95, 1),
            "delta_units_p80":       round(delta_p80, 1),
            "capex_usd_p80":         round(delta_p80 * eq_cost),
            "equipment_unit_cost_usd": eq_cost,
            "demand_mean":           round(float(row["demand_mean"])),
            "n_simulations":         N_SIMULATIONS,
        })

        for label, pct in [("underinvest_p50", 50), ("target_p80", 80), ("overinvest_p95", 95)]:
            threshold = np.percentile(eq_needed, pct)
            scenario_rows.append({
                "site_code":            row["site_code"],
                "test_type":            row["test_type"],
                "scenario":             label,
                "equipment_qty":        round(threshold, 1),
                "probability_sufficient": round(float(np.mean(eq_needed <= threshold)), 4),
                "capex_usd":            round(max(threshold - current_qty, 0) * eq_cost),
            })

    mc_df       = pd.DataFrame(mc_rows)
    scenario_df = pd.DataFrame(scenario_rows)

    total_capex_p80          = mc_df["capex_usd_p80"].sum()
    n_sites_needing_investment = (mc_df["delta_units_p80"] > 0).sum()

    n_mc = upsert_table(conn, mc_df,       "gold_capex_mc_summary")
    n_sc = upsert_table(conn, scenario_df, "gold_capex_mc_scenarios")
    conn.close()

    log.info(f"  Wrote gold_capex_mc_summary: {n_mc:,} rows")
    log.info(f"  Wrote gold_capex_mc_scenarios: {n_sc:,} rows")
    log.info(f"  Total P80 CapEx: ${total_capex_p80:,.0f} | {n_sites_needing_investment} combos need investment")

    return {
        "summary": f"{n_mc:,} combos | P80 CapEx ${total_capex_p80:,.0f} | {n_sites_needing_investment} need investment",
        "mc_rows": n_mc, "scenario_rows": n_sc,
        "total_capex_p80_usd": int(total_capex_p80),
        "sites_needing_investment": int(n_sites_needing_investment),
    }
