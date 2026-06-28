"""
Gold layer: Capacity Math.
Implements the full 5-step capacity formula for NORMAL and MAXIMUM modes.
All intermediate steps stored for auditability.

Step 1: avg_test_time = (handling + test_time)
            × [1 + (1 - yield) × retest_times × test_x_parameter]
Step 2: total_avg_test_time = Step1 / utilization_rate
Step 3: productivity = (hours_per_shift × 3600
            × (1 - allowance_pct) × productivity_pct) / Step2
Step 4: monthly_shifts = working_days × shifts_per_day
Step 5: need = demand / (Step3 × Step4)

Supply: capacity_qty = equip_qty × Step3 × Step4
"""

import math
import pandas as pd
import numpy as np
from src.utils.logger import logger
from src.pipeline.gold.utils import classify_bottleneck, write_gold_table


# ── Retest parameters ──────────────────────────────────────────────────────────

def compute_type1_params() -> tuple[float, float]:
    return 2.0, 0.75


def compute_type2_params(
    yield_retest_1: float,
    yield_retest_2_plus: float,
    retest_quote: float,
) -> tuple[float, float]:
    """
    Type 2: yield-driven retest parameters.
    retest_times = (1 - Y1 + Y2) / Y2
    test_x_parameter = retest_quote
    """
    y1 = yield_retest_1 if yield_retest_1 else 0.80
    y2 = yield_retest_2_plus if yield_retest_2_plus else 0.90
    rq = retest_quote if retest_quote else 0.75

    # Guard against division by zero
    if y2 <= 0:
        y2 = 0.01
    retest_times = (1 - y1 + y2) / y2
    return retest_times, rq


# ── Core 5-step formula ────────────────────────────────────────────────────────

def capacity_steps(
    handling_time_sec: float,
    target_test_time_sec: float,
    target_yield: float,
    retest_times: float,
    test_x_parameter: float,
    utilization_rate: float,
    hours_per_shift: float,
    allowance_pct: float,
    productivity_pct: float,
    working_days: int,
    shifts_per_day: int,
    equip_qty: int,
    demand_qty: float,
) -> dict:
    """
    Compute all 5 capacity steps and derived metrics.
    Returns dict of all intermediate and final values.
    """
    # Guard defaults
    handling      = handling_time_sec or 30.0
    test_time     = target_test_time_sec or 60.0
    yield_val     = max(0.01, min(0.99, target_yield or 0.85))
    util          = max(0.01, min(1.0, utilization_rate or 0.85))
    hrs           = hours_per_shift or 8.0
    allow         = max(0.0, min(0.5, allowance_pct or 0.10))
    prod          = max(0.01, min(1.0, productivity_pct or 0.85))
    wd            = max(1, int(working_days or 20))
    shifts        = max(1, int(shifts_per_day or 2))
    equip         = max(0, int(equip_qty or 0))
    demand        = max(0.0, float(demand_qty or 0.0))
    rt            = max(0.0, float(retest_times or 2.0))
    txp           = max(0.0, float(test_x_parameter or 0.75))

    # Step 1: Average test time with retest multiplier
    retest_multiplier = 1 + (1 - yield_val) * rt * txp
    step1 = (handling + test_time) * retest_multiplier

    # Step 2: Utilization-adjusted test time
    step2 = step1 / util

    # Step 3: Productivity (units per shift per equipment unit)
    # Adjusted formula: includes allowance and productivity factors
    step3_raw      = (hrs * 3600) / step2
    step3_adjusted = (hrs * 3600 * (1 - allow) * prod) / step2

    # Step 4: Monthly shifts
    step4 = wd * shifts

    # Step 5: Equipment units needed (fractional)
    denominator = step3_adjusted * step4
    if denominator <= 0:
        step5 = float("inf")
    else:
        step5 = demand / denominator

    # Supply
    capacity_qty      = equip * step3_adjusted * step4
    supply_per_unit   = step3_adjusted * step4
    gap_qty           = capacity_qty - demand
    utilization_out   = (demand / capacity_qty) if capacity_qty > 0 else float("inf")
    gap_pct           = (gap_qty / demand) if demand > 0 else 0.0

    # Need
    need_ceiling      = math.ceil(step5) if step5 != float("inf") else 9999
    investment_need   = max(0, need_ceiling - equip)
    excess_units      = max(0, equip - need_ceiling)

    return {
        # Intermediate steps (stored for auditability)
        "step1_avg_test_time":          round(step1, 4),
        "step2_total_avg_test_time":    round(step2, 4),
        "step3_productivity_raw":       round(step3_raw, 4),
        "step3_productivity_adjusted":  round(step3_adjusted, 4),
        "step4_monthly_shifts":         step4,
        "step5_need":                   round(step5, 4) if step5 != float("inf") else 9999.0,
        # Supply
        "capacity_qty":                 round(capacity_qty, 2),
        "supply_per_equip_unit":        round(supply_per_unit, 2),
        "supply_headroom_qty":          round(gap_qty, 2),
        # Demand
        "effective_demand_qty":         round(demand, 2),
        # Gap
        "gap_qty":                      round(gap_qty, 2),
        "gap_pct":                      round(gap_pct, 4),
        "utilization_pct":              round(utilization_out, 4),
        # Need
        "need_fractional":              round(step5, 4) if step5 != float("inf") else 9999.0,
        "need_ceiling":                 need_ceiling,
        "investment_need_units":        investment_need,
        "excess_capacity_units":        excess_units,
        # Classification
        "is_bottleneck":                gap_qty < 0,
        "is_excess":                    gap_qty > 0,
        "bottleneck_severity":          classify_bottleneck(gap_pct),
    }


# ── Batch capacity computation ─────────────────────────────────────────────────

def compute_capacity_for_mode(
    gcm_df: pd.DataFrame,
    mode: str,           # "NORMAL" or "MAXIMUM"
    retest_type: str,    # "TYPE1" or "TYPE2"
) -> pd.DataFrame:
    """
    Vectorised capacity computation over the GCM base DataFrame.
    Returns DataFrame with all capacity columns added.
    """
    assert mode in ("NORMAL", "MAXIMUM")
    assert retest_type in ("TYPE1", "TYPE2")

    # Select shift parameters based on mode
    if mode == "NORMAL":
        wd_col     = "working_days_normal"
        shifts_col = "shifts_per_day_normal"
        hrs_col    = "hours_per_shift_normal"
    else:
        wd_col     = "working_days_max"
        shifts_col = "shifts_per_day_max"
        hrs_col    = "hours_per_shift_max"

    rows = []
    for _, row in gcm_df.iterrows():
        # Retest parameters
        if retest_type == "TYPE1":
            rt, txp = compute_type1_params()
        else:
            rt, txp = compute_type2_params(
                row.get("yield_retest_1"),
                row.get("yield_retest_2_plus"),
                row.get("retest_quote"),
            )

        result = capacity_steps(
            handling_time_sec     = row.get("handling_time_sec"),
            target_test_time_sec  = row.get("target_test_time_sec"),
            target_yield          = row.get("target_yield"),
            retest_times          = rt,
            test_x_parameter      = txp,
            utilization_rate      = row.get("utilization_rate"),
            hours_per_shift       = row.get(hrs_col),
            allowance_pct         = row.get("allowance_pct"),
            productivity_pct      = row.get("productivity_pct"),
            working_days          = row.get(wd_col),
            shifts_per_day        = row.get(shifts_col),
            equip_qty             = row.get("equip_qty_available"),
            demand_qty            = row.get("effective_demand_qty"),
        )

        out = {
            "cap_pk":          None,  # filled below
            "gcm_pk":          row["gcm_pk"],
            "site_code":       row["site_code"],
            "factory_code":    row.get("factory_code"),
            "month_key":       row["month_key"],
            "snapshot_id":     row["snapshot_id"],
            "product_number":  row["product_number"],
            "product_family":  row.get("product_family"),
            "platform":        row.get("platform"),
            "product_status":  row.get("product_status"),
            "test_type":       row.get("test_type"),
            "test_category_id":row.get("test_category_id"),
            "equipment_id":    row.get("equipment_id"),
            "equipment_type":  row.get("equipment_type"),
            "equip_qty_available": row.get("equip_qty_available"),
            "capacity_mode":   mode,
            "retest_type":     retest_type,
            "retest_times":    rt,
            "test_x_parameter":txp,
            "utilization_source": "PLANNED",
            **result,
        }
        rows.append(out)

    result_df = pd.DataFrame(rows)

    # Generate surrogate PKs
    import hashlib
    result_df["cap_pk"] = result_df.apply(
        lambda r: hashlib.md5(
            f"{r['gcm_pk']}|{mode}|{retest_type}".encode()
        ).hexdigest(), axis=1
    )
    return result_df


def build_capacity_tables(duck_conn) -> dict:
    """Build gold_cap_normal and gold_cap_maximum."""
    logger.info("  Loading GCM base for capacity math")

    gcm_df = duck_conn.execute("SELECT * FROM gold_gcm_base").df()
    logger.info(f"    GCM rows loaded: {len(gcm_df):,}")

    counts = {}

    for mode in ["NORMAL", "MAXIMUM"]:
        for retest_type in ["TYPE1", "TYPE2"]:
            table_name = f"gold_cap_{mode.lower()}"
            logger.info(f"  Computing {table_name} ({retest_type})")

            cap_df = compute_capacity_for_mode(gcm_df, mode, retest_type)

            if retest_type == "TYPE1":
                # First retest type: create table
                write_gold_table(
                    cap_df, table_name, duck_conn,
                    indexes=["month_key", "site_code",
                             "product_number", "gcm_pk"]
                )
            else:
                # Second retest type: append to existing table
                duck_conn.register("_temp_cap", cap_df)
                duck_conn.execute(f"""
                    INSERT INTO {table_name}
                    SELECT * FROM _temp_cap
                """)
                duck_conn.unregister("_temp_cap")

            counts[f"{table_name}_{retest_type}"] = len(cap_df)
            logger.info(f"    {len(cap_df):,} rows ({retest_type})")

    # Final counts
    for mode in ["NORMAL", "MAXIMUM"]:
        table_name = f"gold_cap_{mode.lower()}"
        final_count = duck_conn.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0]
        counts[table_name] = final_count
        logger.info(f"    {table_name} final: {final_count:,} rows")

    return counts