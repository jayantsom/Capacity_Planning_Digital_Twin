"""
Gold layer: Serving views.
Zero storage cost — views over Gold tables for dashboard consumers.
Recreated on every pipeline run.
"""

from capacity_twin_core.logging import logger

SERVING_VIEWS = {
    "srv_vw_capacity_summary": """
        SELECT
            dvc.site_code,
            rs.region,
            rs.country,
            rs.supplier_name,
            dvc.month_key,
            dvc.product_number,
            dvc.product_family,
            dvc.platform,
            dvc.product_status,
            dvc.test_type,
            dvc.equipment_id,
            dvc.equipment_type,
            dvc.snapshot_id,
            dvc.capacity_mode,
            dvc.retest_type,
            dvc.demand_qty,
            dvc.capacity_qty,
            dvc.gap_qty,
            dvc.gap_pct,
            dvc.utilization_pct,
            dvc.bottleneck_severity,
            dvc.investment_need_units,
            dvc.excess_capacity_units,
            dvc.flexibility_pct
        FROM gold_dmnd_vs_cap dvc
        LEFT JOIN slvr_ref_site rs
            ON dvc.site_code = rs.site_code
    """,

    "srv_vw_bottleneck_heatmap": """
        SELECT
            b.site_code,
            rs.region,
            rs.supplier_name,
            b.month_key,
            b.test_type,
            b.equipment_type,
            b.capacity_mode,
            b.retest_type,
            b.snapshot_id,
            b.bottleneck_severity,
            b.worst_gap_qty,
            b.total_investment_need_units,
            b.affected_products,
            b.affected_demand_qty,
            b.min_gap_pct,
            b.avg_gap_pct,
            b.avg_utilization_pct,
            -- Severity numeric score for heatmap coloring
            CASE b.bottleneck_severity
                WHEN 'CRITICAL'  THEN 6
                WHEN 'HIGH'      THEN 5
                WHEN 'MEDIUM'    THEN 4
                WHEN 'LOW'       THEN 3
                WHEN 'BALANCED'  THEN 2
                WHEN 'EXCESS'    THEN 1
                ELSE 0
            END                 AS severity_score
        FROM gold_bottleneck b
        LEFT JOIN slvr_ref_site rs
            ON b.site_code = rs.site_code
    """,

    "srv_vw_equipment_utilization": """
        SELECT
            dvc.site_code,
            rs.region,
            dvc.month_key,
            dvc.test_type,
            dvc.equipment_id,
            dvc.equipment_type,
            dvc.capacity_mode,
            dvc.retest_type,
            dvc.snapshot_id,
            AVG(dvc.utilization_pct)        AS avg_utilization_pct,
            MAX(dvc.utilization_pct)        AS max_utilization_pct,
            MIN(dvc.capacity_qty)           AS min_capacity_qty,
            SUM(dvc.demand_qty)             AS total_demand_qty,
            SUM(dvc.investment_need_units)  AS total_investment_need
        FROM gold_dmnd_vs_cap dvc
        LEFT JOIN slvr_ref_site rs ON dvc.site_code = rs.site_code
        GROUP BY
            dvc.site_code, rs.region, dvc.month_key,
            dvc.test_type, dvc.equipment_id, dvc.equipment_type,
            dvc.capacity_mode, dvc.retest_type, dvc.snapshot_id
    """,

    "srv_vw_oee_trend": """
        SELECT
            o.site_code,
            rs.region,
            rs.supplier_name,
            o.month_key,
            o.test_type,
            o.test_category_id,
            o.availability_pct,
            o.performance_pct,
            o.quality_pct,
            o.oee_pct,
            o.actual_throughput,
            o.total_passed,
            o.total_produced,
            o.avg_downtime_hr,
            -- OEE benchmark flags
            CASE
                WHEN o.oee_pct >= 0.85 THEN 'WORLD_CLASS'
                WHEN o.oee_pct >= 0.65 THEN 'GOOD'
                WHEN o.oee_pct >= 0.50 THEN 'AVERAGE'
                ELSE                        'POOR'
            END                             AS oee_tier
        FROM gold_oee_metrics o
        LEFT JOIN slvr_ref_site rs
            ON o.site_code = rs.site_code
    """,

    "srv_vw_forecast_accuracy": """
        SELECT
            fa.site_code,
            rs.region,
            fa.product_number,
            pm.product_family,
            pm.platform,
            pm.product_status,
            fa.month_key,
            fa.snapshot_id,
            fa.snapshot_date,
            fa.forecast_qty,
            fa.actual_qty,
            fa.abs_error,
            fa.pct_error,
            fa.bias,
            -- MAPE contribution
            fa.pct_error                    AS mape_contribution,
            -- Bias direction
            CASE
                WHEN fa.bias > 0 THEN 'OVER_FORECAST'
                WHEN fa.bias < 0 THEN 'UNDER_FORECAST'
                ELSE                  'ACCURATE'
            END                             AS bias_direction
        FROM gold_forecast_accuracy fa
        LEFT JOIN slvr_ref_site rs  ON fa.site_code     = rs.site_code
        LEFT JOIN slvr_prod_master pm ON fa.product_number = pm.product_number
    """,

    "srv_vw_mi_actuals_summary": """
        SELECT
            ca.site_code,
            rs.region,
            ca.product_number,
            pm.product_family,
            ca.test_type,
            ca.month_key,
            ca.snapshot_id,
            ca.actual_passed_qty,
            ca.actual_total_qty,
            ca.actual_yield_avg,
            ca.actual_test_duration_avg,
            ca.actual_throughput_avg,
            ca.actual_downtime_avg,
            ca.yield_variance,
            ca.test_time_variance_sec,
            -- Flag significant variances
            CASE
                WHEN ABS(ca.yield_variance) > 0.05 THEN 'SIGNIFICANT'
                WHEN ABS(ca.yield_variance) > 0.02 THEN 'MODERATE'
                ELSE 'WITHIN_TOLERANCE'
            END                             AS yield_variance_flag
        FROM gold_cap_actual ca
        LEFT JOIN slvr_ref_site rs    ON ca.site_code     = rs.site_code
        LEFT JOIN slvr_prod_master pm ON ca.product_number = pm.product_number
    """,
}


def build_serving_views(duck_conn) -> int:
    logger.info("  Building serving views")
    count = 0
    for view_name, sql in SERVING_VIEWS.items():
        duck_conn.execute(f"DROP VIEW IF EXISTS {view_name}")
        duck_conn.execute(f"CREATE VIEW {view_name} AS {sql}")
        duck_conn.execute(f"SELECT * FROM {view_name} LIMIT 1").fetchall()
        logger.info(f"    {view_name} ✓")
        count += 1
    return count