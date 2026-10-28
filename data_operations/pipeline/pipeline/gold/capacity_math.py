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

from capacity_twin_core.capacity.formulas import (
    ResourceBehavior,
    calculate_effective_parallel_duts,
    calculate_scenario_gap,
    classify_bottleneck,
)
from capacity_twin_core.logging import logger
from data_operations.pipeline.pipeline.gold.utils import write_gold_table


def _number_or_default(value: float | None, default: float) -> float:
    """Use a default only for missing values, while preserving valid zeroes."""
    if value is None or pd.isna(value):
        return default
    return float(value)


# ── Retest parameters ──────────────────────────────────────────────────────────

def compute_type1_params() -> tuple[float, float]:
    return 2.0, 0.75


def compute_no_retest_params() -> tuple[float, float]:
    """Return the governed zero-retest option."""
    return 0.0, 0.0


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
    y1 = _number_or_default(yield_retest_1, 0.80)
    y2 = _number_or_default(yield_retest_2_plus, 0.90)
    rq = _number_or_default(retest_quote, 0.75)

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
    parallel_dut_factor: float = 1.0,
) -> dict:
    """
    Compute all 5 capacity steps and derived metrics.
    Returns dict of all intermediate and final values.
    """
    # Guard defaults
    handling = max(0.0, _number_or_default(handling_time_sec, 30.0))
    test_time = max(0.0, _number_or_default(target_test_time_sec, 60.0))
    yield_val = max(0.01, min(0.99, _number_or_default(target_yield, 0.85)))
    util = max(0.01, min(1.0, _number_or_default(utilization_rate, 0.85)))
    hrs = max(0.0, _number_or_default(hours_per_shift, 8.0))
    allow = max(0.0, min(0.5, _number_or_default(allowance_pct, 0.10)))
    prod = max(0.0, min(1.0, _number_or_default(productivity_pct, 0.85)))
    wd = max(0, int(_number_or_default(working_days, 20)))
    shifts = max(0, int(_number_or_default(shifts_per_day, 2)))
    equip = max(0, int(_number_or_default(equip_qty, 0)))
    demand = max(0.0, _number_or_default(demand_qty, 0.0))
    dut_factor = max(0.0, _number_or_default(parallel_dut_factor, 1.0))
    rt = max(0.0, _number_or_default(retest_times, 2.0))
    txp = max(0.0, _number_or_default(test_x_parameter, 0.75))

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
    denominator = step3_adjusted * step4 * dut_factor
    if denominator <= 0:
        step5 = float("inf")
    else:
        step5 = demand / denominator

    # Supply
    capacity_qty      = equip * step3_adjusted * step4 * dut_factor
    supply_per_unit   = step3_adjusted * step4 * dut_factor
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
        "workload_seconds":             round(demand * step1 / max(dut_factor, 0.000001), 4),
        "workload_resource_hours":      round(
            demand * step2 / max(dut_factor * 3600.0, 0.000001), 4
        ),
        "available_resource_hours":     round(
            equip * hrs * wd * shifts * (1 - allow) * prod, 4
        ),
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


def resource_scenario_summary(
    behavior: ResourceBehavior,
    demands: list[float],
    capacities: list[float],
    *,
    multi_dut_factor: float = 1.0,
) -> dict[str, float | str]:
    """Apply the shared resource contract to one pooled capacity scenario."""
    demand, capacity, gap = calculate_scenario_gap(
        behavior,
        demands,
        capacities,
        multi_dut_factor=multi_dut_factor,
    )
    gap_ratio = gap / demand if demand else 0.0
    return {
        "resource_behavior": behavior.value,
        "demand_qty": demand,
        "capacity_qty": capacity,
        "gap_qty": gap,
        "gap_ratio": gap_ratio,
        "bottleneck_severity": classify_bottleneck(gap_ratio),
    }


# ── Batch capacity computation ─────────────────────────────────────────────────

def compute_capacity_for_mode(
    gcm_df: pd.DataFrame,
    mode: str,           # "NORMAL" or "MAXIMUM"
    retest_type: str,    # "NONE", "TYPE1", or "TYPE2"
) -> pd.DataFrame:
    """
    Vectorised capacity computation over the GCM base DataFrame.
    Returns DataFrame with all capacity columns added.
    """
    assert mode in ("NORMAL", "MAXIMUM")
    assert retest_type in ("NONE", "TYPE1", "TYPE2")

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
        if retest_type == "NONE":
            rt, txp = compute_no_retest_params()
        elif retest_type == "TYPE1":
            rt, txp = compute_type1_params()
        else:
            rt, txp = compute_type2_params(
                row.get("yield_retest_1"),
                row.get("yield_retest_2_plus"),
                row.get("retest_quote"),
            )

        raw_behavior = row.get("resource_behavior")
        if raw_behavior is None or pd.isna(raw_behavior):
            raise ValueError("Promoted capacity rows require a governed resource_behavior")
        try:
            behavior = ResourceBehavior(raw_behavior)
        except ValueError as error:
            raise ValueError(f"Unknown governed resource behavior: {raw_behavior}") from error
        parallel_duts = 1.0
        if behavior is ResourceBehavior.MULTI_DUT:
            parallel_duts = calculate_effective_parallel_duts(
                tester_channels=int(_number_or_default(row.get("tester_channels"), 1)),
                licensed_ports=int(
                    _number_or_default(row.get("enabled_licensed_ports"), 1)
                ),
                fixture_cavities=int(_number_or_default(row.get("fixture_cavities"), 1)),
                handler_sockets=int(_number_or_default(row.get("handler_sockets"), 1)),
                parallel_efficiency=_number_or_default(
                    row.get("parallel_efficiency"), 1.0
                ),
            )

        result = capacity_steps(
            handling_time_sec     = (
                0.0 if row.get("governed_cycle_time_sec") is not None
                else row.get("handling_time_sec")
            ),
            target_test_time_sec  = row.get(
                "governed_cycle_time_sec",
                row.get("target_test_time_sec"),
            ),
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
            parallel_dut_factor   = parallel_duts,
        )

        out = {
            "cap_pk":          None,  # filled below
            "gcm_pk":          row["gcm_pk"],
            "site_code":       row["site_code"],
            "factory_code":    row.get("factory_code"),
            "month_key":       row["month_key"],
            "planning_version_id":     row["planning_version_id"],
            "plan_as_of_date": row.get("plan_as_of_date"),
            "product_number":  row["product_number"],
            "product_family":  row.get("product_family"),
            "platform":        row.get("platform"),
            "test_type":       row.get("test_type"),
            "test_category_id":row.get("test_category_id"),
            "equipment_id":    row.get("equipment_id"),
            "equipment_type":  row.get("equipment_type"),
            "resource_behavior": behavior.value,
            "route_id": row.get("route_id"),
            "route_step_id": row.get("route_step_id"),
            "route_step_sequence": row.get("route_step_sequence"),
            "route_step_demand_qty": row.get(
                "route_step_demand_qty", row.get("effective_demand_qty")
            ),
            "qualification_id": row.get("qualification_id"),
            "pool_id": row.get("pool_id"),
            "pool_behavior": row.get("pool_behavior"),
            "paired_fixture_resource_id": row.get("paired_fixture_resource_id"),
            "handler_resource_id": row.get("handler_resource_id"),
            "tester_channels": row.get("tester_channels"),
            "enabled_licensed_ports": row.get("enabled_licensed_ports"),
            "tester_fixture_slots": row.get("tester_fixture_slots"),
            "fixture_cavities": row.get("fixture_cavities"),
            "handler_sockets": row.get("handler_sockets"),
            "fixtures_required_per_system": row.get("fixtures_required_per_system"),
            "execution_mode": row.get("execution_mode"),
            "batch_cycle_time_sec": row.get("batch_cycle_time_sec"),
            "changeover_time_sec": row.get("changeover_time_sec"),
            "parallel_efficiency": row.get("parallel_efficiency"),
            "governed_cycle_time_sec": row.get("governed_cycle_time_sec"),
            "effective_parallel_duts": parallel_duts,
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
        for retest_type in ["NONE", "TYPE1", "TYPE2"]:
            table_name = f"gold_cap_{mode.lower()}"
            logger.info(f"  Computing {table_name} ({retest_type})")

            cap_df = compute_capacity_for_mode(gcm_df, mode, retest_type)

            if retest_type == "NONE":
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


def _build_workload_resource_scenario_table(duck_conn) -> int:
    """Constrain pooled resources in resource hours without unit fan-out."""
    duck_conn.execute("DROP TABLE IF EXISTS gold_resource_scenarios")
    duck_conn.execute(
        """
        CREATE TABLE gold_resource_scenarios AS
        WITH capacity_data AS (
            SELECT * FROM gold_cap_normal
            UNION ALL BY NAME
            SELECT * FROM gold_cap_maximum
        ),
        resource_grain AS (
            SELECT
                site_code,
                month_key,
                planning_version_id,
                product_number,
                route_step_id,
                test_type,
                capacity_mode,
                retest_type,
                resource_behavior,
                pool_id,
                equipment_id,
                MAX(equipment_type) AS equipment_type,
                MAX(route_step_demand_qty) AS route_step_demand_qty,
                MAX(workload_seconds) AS workload_seconds,
                MAX(workload_resource_hours) AS workload_resource_hours,
                MAX(available_resource_hours) AS available_resource_hours,
                MAX(capacity_qty) AS product_mix_capacity_qty
            FROM capacity_data
            GROUP BY ALL
        ),
        grouped AS (
            SELECT
                site_code,
                month_key,
                planning_version_id,
                CASE WHEN resource_behavior = 'SHARED_POOL'
                     THEN NULL ELSE product_number END AS product_number,
                CASE WHEN resource_behavior = 'SHARED_POOL'
                     THEN NULL ELSE route_step_id END AS route_step_id,
                test_type,
                capacity_mode,
                retest_type,
                resource_behavior,
                COALESCE(pool_id, equipment_id) AS resource_constraint_id,
                string_agg(
                    DISTINCT equipment_id, ',' ORDER BY equipment_id
                ) AS equipment_id,
                string_agg(
                    DISTINCT equipment_type, ',' ORDER BY equipment_type
                ) AS equipment_type,
                COUNT(DISTINCT product_number) AS affected_products,
                MAX(route_step_demand_qty) AS route_step_demand_qty,
                SUM(workload_seconds) AS workload_seconds,
                SUM(workload_resource_hours) AS required_resource_hours,
                CASE
                    WHEN resource_behavior IN ('PAIRED_FIXTURE', 'SERIAL_STEP')
                    THEN MIN(available_resource_hours)
                    ELSE SUM(available_resource_hours)
                END AS available_resource_hours,
                CASE
                    WHEN resource_behavior IN ('SHARED_POOL', 'ALTERNATIVE_POOL')
                    THEN NULL
                    ELSE SUM(product_mix_capacity_qty)
                END AS declared_mix_capacity_qty
            FROM resource_grain
            GROUP BY
                site_code, month_key, planning_version_id,
                CASE WHEN resource_behavior = 'SHARED_POOL'
                     THEN NULL ELSE product_number END,
                CASE WHEN resource_behavior = 'SHARED_POOL'
                     THEN NULL ELSE route_step_id END,
                test_type, capacity_mode, retest_type, resource_behavior,
                COALESCE(pool_id, equipment_id)
        )
        SELECT
            md5(
                site_code || '|' || CAST(month_key AS VARCHAR) || '|' ||
                planning_version_id || '|' || COALESCE(product_number, 'SHARED') ||
                '|' || COALESCE(route_step_id, 'POOL') || '|' ||
                resource_constraint_id || '|' || capacity_mode || '|' || retest_type
            ) AS resource_scenario_pk,
            *,
            available_resource_hours - required_resource_hours AS gap_resource_hours,
            CASE WHEN required_resource_hours > 0
                 THEN (available_resource_hours - required_resource_hours)
                    / required_resource_hours
                 ELSE 0 END AS gap_ratio,
            CASE
                WHEN required_resource_hours <= 0 THEN 'BALANCED'
                WHEN (available_resource_hours - required_resource_hours)
                     / required_resource_hours < -0.15 THEN 'CRITICAL'
                WHEN (available_resource_hours - required_resource_hours)
                     / required_resource_hours < -0.08 THEN 'HIGH'
                WHEN (available_resource_hours - required_resource_hours)
                     / required_resource_hours < -0.03 THEN 'MEDIUM'
                WHEN available_resource_hours < required_resource_hours THEN 'LOW'
                WHEN (available_resource_hours - required_resource_hours)
                     / required_resource_hours <= 0.05 THEN 'BALANCED'
                ELSE 'EXCESS'
            END AS bottleneck_severity
        FROM grouped
        """
    )
    for column in ("month_key", "site_code", "resource_behavior"):
        duck_conn.execute(
            f"CREATE INDEX idx_gold_resource_scenarios_{column} "
            f"ON gold_resource_scenarios ({column})"
        )
    return int(
        duck_conn.execute("SELECT COUNT(*) FROM gold_resource_scenarios").fetchone()[0]
    )


def build_resource_scenario_table(duck_conn) -> int:
    """Publish resource scenarios with set-based DuckDB aggregation."""
    columns = {
        row[0] for row in duck_conn.execute("DESCRIBE gold_cap_normal").fetchall()
    }
    if {
        "workload_seconds",
        "workload_resource_hours",
        "available_resource_hours",
        "route_step_id",
    } <= columns:
        count = _build_workload_resource_scenario_table(duck_conn)
        logger.info(f"    gold_resource_scenarios: {count:,} rows")
        return count
    duck_conn.execute("DROP TABLE IF EXISTS gold_resource_scenarios")
    duck_conn.execute(
        """
        CREATE TABLE gold_resource_scenarios AS
        WITH capacity_data AS (
            SELECT * FROM gold_cap_normal
            UNION ALL BY NAME
            SELECT * FROM gold_cap_maximum
        ),
        non_shared_equipment AS (
            SELECT
                site_code,
                month_key,
                planning_version_id,
                product_number,
                test_type,
                capacity_mode,
                retest_type,
                equipment_id,
                MAX(equipment_type) AS equipment_type,
                MAX(resource_behavior) AS resource_behavior,
                MAX(effective_demand_qty) AS demand_qty,
                MIN(capacity_qty) AS equipment_capacity
            FROM capacity_data
            WHERE resource_behavior <> 'SHARED_POOL'
            GROUP BY
                site_code,
                month_key,
                planning_version_id,
                product_number,
                test_type,
                capacity_mode,
                retest_type,
                equipment_id
        ),
        non_shared_grouped AS (
            SELECT
                site_code,
                month_key,
                planning_version_id,
                product_number,
                test_type,
                capacity_mode,
                retest_type,
                string_agg(
                    DISTINCT CAST(equipment_id AS VARCHAR),
                    ',' ORDER BY CAST(equipment_id AS VARCHAR)
                ) FILTER (WHERE equipment_id IS NOT NULL) AS equipment_id,
                string_agg(
                    DISTINCT CAST(equipment_type AS VARCHAR),
                    ',' ORDER BY CAST(equipment_type AS VARCHAR)
                ) FILTER (WHERE equipment_type IS NOT NULL) AS equipment_type,
                COUNT(DISTINCT equipment_id) AS equipment_count,
                COUNT(DISTINCT resource_behavior) AS behavior_count,
                MIN(resource_behavior) AS declared_behavior,
                BOOL_AND(resource_behavior = 'DEDICATED') AS all_dedicated,
                BOOL_OR(UPPER(equipment_type) = 'SYSTEM') AS has_system,
                BOOL_OR(UPPER(equipment_type) = 'FIXTURE') AS has_fixture,
                MAX(demand_qty) AS demand_qty,
                SUM(equipment_capacity) AS summed_capacity,
                MIN(equipment_capacity) AS constrained_capacity
            FROM non_shared_equipment
            GROUP BY
                site_code,
                month_key,
                planning_version_id,
                product_number,
                test_type,
                capacity_mode,
                retest_type
        ),
        non_shared_classified AS (
            SELECT
                *,
                CASE
                    WHEN all_dedicated AND equipment_count > 1
                         AND has_system AND has_fixture
                        THEN 'PAIRED_FIXTURE'
                    WHEN all_dedicated AND equipment_count > 1
                        THEN 'ALTERNATIVE_POOL'
                    WHEN behavior_count = 1
                        THEN declared_behavior
                    ELSE 'ALTERNATIVE_POOL'
                END AS resolved_behavior
            FROM non_shared_grouped
        ),
        non_shared_result AS (
            SELECT
                site_code,
                month_key,
                planning_version_id,
                product_number,
                test_type,
                equipment_id,
                capacity_mode,
                retest_type,
                equipment_type,
                1::BIGINT AS affected_products,
                resolved_behavior AS resource_behavior,
                demand_qty,
                CASE
                    WHEN resolved_behavior IN ('SERIAL_STEP', 'PAIRED_FIXTURE')
                        THEN constrained_capacity
                    ELSE summed_capacity
                END AS capacity_qty
            FROM non_shared_classified
        ),
        shared_result AS (
            SELECT
                site_code,
                month_key,
                planning_version_id,
                NULL::VARCHAR AS product_number,
                test_type,
                CAST(equipment_id AS VARCHAR) AS equipment_id,
                capacity_mode,
                retest_type,
                string_agg(
                    DISTINCT CAST(equipment_type AS VARCHAR),
                    ',' ORDER BY CAST(equipment_type AS VARCHAR)
                ) FILTER (WHERE equipment_type IS NOT NULL) AS equipment_type,
                COUNT(DISTINCT product_number) AS affected_products,
                'SHARED_POOL' AS resource_behavior,
                SUM(effective_demand_qty) AS demand_qty,
                MIN(capacity_qty) AS capacity_qty
            FROM capacity_data
            WHERE resource_behavior = 'SHARED_POOL'
            GROUP BY
                site_code,
                month_key,
                planning_version_id,
                test_type,
                equipment_id,
                capacity_mode,
                retest_type
        ),
        scenarios AS (
            SELECT * FROM non_shared_result
            UNION ALL BY NAME
            SELECT * FROM shared_result
        ),
        with_gap AS (
            SELECT
                *,
                capacity_qty - demand_qty AS gap_qty,
                CASE
                    WHEN demand_qty > 0
                        THEN (capacity_qty - demand_qty) / demand_qty
                    ELSE 0.0
                END AS gap_ratio
            FROM scenarios
        )
        SELECT
            md5(
                COALESCE(CAST(site_code AS VARCHAR), '') || '|' ||
                COALESCE(CAST(month_key AS VARCHAR), '') || '|' ||
                COALESCE(CAST(planning_version_id AS VARCHAR), '') || '|' ||
                COALESCE(CAST(product_number AS VARCHAR), 'None') || '|' ||
                COALESCE(CAST(test_type AS VARCHAR), '') || '|' ||
                COALESCE(CAST(equipment_id AS VARCHAR), '') || '|' ||
                COALESCE(CAST(capacity_mode AS VARCHAR), '') || '|' ||
                COALESCE(CAST(retest_type AS VARCHAR), '')
            ) AS resource_scenario_pk,
            *,
            CASE
                WHEN gap_ratio < -0.15 THEN 'CRITICAL'
                WHEN gap_ratio < -0.08 THEN 'HIGH'
                WHEN gap_ratio < -0.03 THEN 'MEDIUM'
                WHEN gap_ratio < 0 THEN 'LOW'
                WHEN gap_ratio <= 0.05 THEN 'BALANCED'
                ELSE 'EXCESS'
            END AS bottleneck_severity
        FROM with_gap
        """
    )
    for column in ["month_key", "site_code", "resource_behavior"]:
        duck_conn.execute(
            f"""
            CREATE INDEX idx_gold_resource_scenarios_{column}
            ON gold_resource_scenarios ({column})
            """
        )
    count = duck_conn.execute(
        "SELECT COUNT(*) FROM gold_resource_scenarios"
    ).fetchone()[0]
    logger.info(f"    gold_resource_scenarios: {count:,} rows")
    return count