"""Self-contained materialized Serving contracts built from attached candidates."""

from capacity_twin_core.logging import logger

SERVING_VIEWS = {
    "srv_reference_site": """
        SELECT site_code, site_name, factory_code, region, country, supplier_name
        FROM slvr_ref_site
        WHERE is_valid
    """,
    "srv_reference_product": """
        SELECT product_number, product_description, product_family, platform,
               product_status
        FROM slvr_prod_master
        WHERE is_valid
    """,
    "srv_reference_test_type": """
        SELECT test_type, test_category_name, test_category_id
        FROM slvr_ref_test_type
        WHERE is_valid
    """,
    "srv_reference_equipment": """
        SELECT equipment_id, equipment_name, equipment_type, manufacturer
        FROM slvr_ref_equipment
        WHERE is_valid
    """,
    "srv_vw_capacity_summary": """
        SELECT
            dvc.site_code,
            rs.site_name,
            rs.region,
            rs.country,
            rs.supplier_name,
            dvc.month_key,
            dvc.product_number,
            pm.product_description,
            dvc.product_family,
            dvc.platform,
            dvc.product_status,
            dvc.test_type,
            dvc.equipment_id,
            dvc.equipment_type,
            dvc.planning_version_id,
            dvc.plan_as_of_date,
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
        LEFT JOIN slvr_prod_master pm
            ON dvc.product_number = pm.product_number
    """,
    "srv_vw_bottleneck_heatmap": """
        SELECT
            b.site_code,
            rs.site_name,
            rs.region,
            rs.supplier_name,
            b.month_key,
            b.test_type,
            b.equipment_type,
            b.capacity_mode,
            b.retest_type,
            b.planning_version_id,
            b.plan_as_of_date,
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
            rs.site_name,
            rs.region,
            dvc.month_key,
            dvc.test_type,
            dvc.equipment_id,
            dvc.equipment_type,
            dvc.capacity_mode,
            dvc.retest_type,
            dvc.planning_version_id,
            dvc.plan_as_of_date,
            AVG(dvc.utilization_pct)        AS avg_utilization_pct,
            MAX(dvc.utilization_pct)        AS max_utilization_pct,
            MIN(dvc.capacity_qty)           AS min_capacity_qty,
            SUM(dvc.demand_qty)             AS total_demand_qty,
            SUM(dvc.investment_need_units)  AS total_investment_need
        FROM gold_dmnd_vs_cap dvc
        LEFT JOIN slvr_ref_site rs ON dvc.site_code = rs.site_code
        GROUP BY
            dvc.site_code, rs.site_name, rs.region, dvc.month_key,
            dvc.test_type, dvc.equipment_id, dvc.equipment_type,
            dvc.capacity_mode, dvc.retest_type, dvc.planning_version_id,
            dvc.plan_as_of_date
    """,
    "srv_vw_oee_trend": """
        SELECT
            o.site_code,
            rs.site_name,
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
            rs.site_name,
            rs.region,
            fa.product_number,
            pm.product_description,
            pm.product_family,
            pm.platform,
            pm.product_status,
            fa.month_key,
            fa.planning_version_id,
            fa.plan_as_of_date,
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
    "srv_vw_machine_actuals_summary": """
        SELECT
            ca.site_code,
            rs.site_name,
            rs.region,
            ca.product_number,
            pm.product_description,
            pm.product_family,
            ca.test_type,
            ca.month_key,
            ca.actual_passed_qty,
            ca.actual_total_qty,
            ca.actual_yield_avg,
            ca.actual_test_duration_avg,
            ca.actual_throughput_avg,
            ca.actual_downtime_seconds,
            ca.output_unit,
            ca.output_method
        FROM gold_cap_actual ca
        LEFT JOIN slvr_ref_site rs    ON ca.site_code     = rs.site_code
        LEFT JOIN slvr_prod_master pm ON ca.product_number = pm.product_number
    """,
    "srv_demonstrated_capacity": """
        SELECT
            demonstrated.*,
            site.site_name,
            site.region,
            product.product_description,
            product.product_family
        FROM gold_demonstrated_capacity demonstrated
        LEFT JOIN slvr_ref_site site
          ON demonstrated.site_code = site.site_code
        LEFT JOIN slvr_prod_master product
          ON demonstrated.product_number = product.product_number
    """,
    "srv_resource_constraints": """
        SELECT scenario.*, site.site_name, product.product_description,
               test_type.test_category_name, equipment.equipment_name
        FROM gold_resource_scenarios scenario
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_prod_master product USING (product_number)
        LEFT JOIN slvr_ref_test_type test_type USING (test_type)
        LEFT JOIN slvr_ref_equipment equipment
          ON scenario.resource_constraint_id = equipment.equipment_id
    """,
    "srv_ml_feature_store": """
        SELECT * FROM gold_ml_feature_store
    """,
    "srv_gcm_resource_contract": """
        SELECT * FROM gold_gcm_base
    """,
    "srv_oee_metrics": """
        SELECT * FROM gold_oee_metrics
    """,
    "srv_actual_output": """
        SELECT * FROM gold_cap_actual
    """,
    "srv_vw_operational_performance": """
        SELECT
            op.period_grain,
            op.period_key,
            op.period_start,
            op.period_end,
            op.period_complete,
            op.days_present,
            op.observation_rows,
            op.factory_code,
            op.site_code,
            rs.site_name,
            op.product_number,
            pm.product_description,
            op.test_type,
            tt.test_category_name AS test_type_name,
            op.passed_qty,
            op.failed_qty,
            op.tested_qty,
            op.yield_pct,
            op.first_pass_qty,
            op.first_fail_qty,
            op.first_pass_yield_pct,
            op.downtime_seconds,
            op.productive_seconds,
            op.downtime_hours,
            op.weighted_test_time_sec,
            op.weighted_handling_time_sec,
            op.weighted_throughput_uph,
            op.availability_pct,
            op.performance_pct,
            op.quality_pct,
            op.oee_pct,
            op.pipeline_run_id
        FROM gold_operational_performance op
        LEFT JOIN slvr_ref_site rs ON op.site_code = rs.site_code
        LEFT JOIN slvr_prod_master pm ON op.product_number = pm.product_number
        LEFT JOIN slvr_ref_test_type tt ON op.test_type = tt.test_type
    """,
    "srv_vw_operational_events": """
        SELECT
            oe.period_grain,
            oe.period_key,
            oe.period_start,
            oe.period_end,
            oe.factory_code,
            oe.site_code,
            rs.site_name,
            oe.product_number,
            pm.product_description,
            oe.test_type,
            tt.test_category_name AS test_type_name,
            oe.severity,
            oe.error_code,
            oe.event_count,
            oe.pipeline_run_id
        FROM gold_operational_events oe
        LEFT JOIN slvr_ref_site rs ON oe.site_code = rs.site_code
        LEFT JOIN slvr_prod_master pm ON oe.product_number = pm.product_number
        LEFT JOIN slvr_ref_test_type tt ON oe.test_type = tt.test_type
    """,
    "srv_sop_balance": """
        SELECT balance.*, site.site_name, product.product_description
        FROM gold_sop_balance balance
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_prod_master product USING (product_number)
    """,
    "srv_npi_readiness": """
        SELECT readiness.*, site.site_name, product.product_description
        FROM gold_npi_readiness readiness
        LEFT JOIN slvr_ref_site site ON readiness.lead_site_code = site.site_code
        LEFT JOIN slvr_prod_master product USING (product_number)
    """,
    "srv_npi_ramp": """
        SELECT ramp.*, site.site_name, product.product_description
        FROM gold_npi_ramp ramp
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_prod_master product USING (product_number)
    """,
    "srv_npi_stage_gate": """
        SELECT
            gate.stage_gate_id,
            gate.program_id,
            program.program_name,
            program.product_number,
            program.lead_site_code,
            site.site_name,
            product.product_description,
            gate.gate_sequence,
            gate.gate_name,
            gate.planned_gate_date,
            gate.actual_gate_date,
            gate.gate_status,
            gate.approval_evidence_id
        FROM slvr_npi_stage_gate gate
        JOIN slvr_npi_program program USING (program_id)
        LEFT JOIN slvr_ref_site site ON program.lead_site_code = site.site_code
        LEFT JOIN slvr_prod_master product USING (product_number)
        WHERE gate.is_valid AND program.is_valid
    """,
    "srv_operations_wip": """
        SELECT flow.*, site.site_name, product.product_description,
               equipment.equipment_name
        FROM gold_operations_wip flow
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_prod_master product USING (product_number)
        LEFT JOIN slvr_ref_equipment equipment ON flow.resource_id = equipment.equipment_id
    """,
    "srv_operations_queue": """
        SELECT flow.*, site.site_name, equipment.equipment_name
        FROM gold_operations_queue flow
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_ref_equipment equipment ON flow.resource_id = equipment.equipment_id
    """,
    "srv_operations_cycle_time": """
        SELECT flow.*, site.site_name, product.product_description
        FROM gold_operations_cycle_time flow
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_prod_master product USING (product_number)
    """,
    "srv_operations_throughput": """
        SELECT flow.*, site.site_name, equipment.equipment_name
        FROM gold_operations_throughput flow
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_ref_equipment equipment ON flow.resource_id = equipment.equipment_id
    """,
    "srv_operations_rework": """
        SELECT flow.*, site.site_name, product.product_description
        FROM gold_operations_rework flow
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_prod_master product USING (product_number)
    """,
    "srv_operations_route_adherence": """
        SELECT flow.*, site.site_name, product.product_description
        FROM gold_operations_route_adherence flow
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_prod_master product USING (product_number)
    """,
    "srv_operations_schedule_attainment": """
        SELECT flow.*, site.site_name, product.product_description
        FROM gold_operations_schedule_attainment flow
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_prod_master product USING (product_number)
    """,
    "srv_operations_bottleneck_movement": """
        SELECT flow.*, site.site_name, equipment.equipment_name
        FROM gold_operations_bottleneck_movement flow
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_ref_equipment equipment ON flow.resource_id = equipment.equipment_id
    """,
    "srv_operations_route_flow": """
        WITH flow AS (
            SELECT
                movement_date,
                site_code,
                product_number,
                route_id,
                route_step_sequence,
                from_operation,
                to_operation,
                resource_id,
                COUNT(*) AS movement_count,
                COUNT(DISTINCT lot_id) AS lot_count,
                SUM(input_quantity_ea) AS input_quantity_ea,
                SUM(output_quantity_ea) AS output_quantity_ea,
                COUNT(*) FILTER (WHERE disposition_code = 'REWORK') AS rework_count,
                'EA' AS quantity_unit
            FROM gold_operations_event
            GROUP BY ALL
        )
        SELECT flow.*, site.site_name, product.product_description,
               equipment.equipment_name
        FROM flow
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_prod_master product USING (product_number)
        LEFT JOIN slvr_ref_equipment equipment ON flow.resource_id = equipment.equipment_id
    """,
    "srv_scenario_inputs": """
        SELECT scenario.*, site.site_name, product.product_description,
               equipment.equipment_name
        FROM gold_scenario_inputs scenario
        LEFT JOIN slvr_ref_site site USING (site_code)
        LEFT JOIN slvr_prod_master product USING (product_number)
        LEFT JOIN slvr_ref_equipment equipment ON scenario.resource_id = equipment.equipment_id
    """,
    "srv_equipment_cost_reference": """
        SELECT cost.*, equipment.equipment_name, equipment.manufacturer
        FROM gold_equipment_cost_reference cost
        LEFT JOIN slvr_ref_equipment equipment USING (equipment_id)
    """,
}


def build_serving_views(duck_conn) -> int:
    """Materialize every Serving object so the file has no attachment dependency."""
    logger.info("  Materializing serving tables")
    count = 0
    for table_name, sql in SERVING_VIEWS.items():
        duck_conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        duck_conn.execute(f'CREATE TABLE "{table_name}" AS {sql}')
        duck_conn.execute(f'SELECT * FROM "{table_name}" LIMIT 1').fetchall()
        logger.info(f"    {table_name} ✓")
        count += 1
    return count
