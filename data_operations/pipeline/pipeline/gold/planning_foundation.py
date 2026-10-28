"""Gold planning facts for S&OP, NPI, operations flow, and session scenarios."""

from __future__ import annotations

from data_operations.pipeline.pipeline.database_staging import assert_unique_grain


def build_sop_balance(connection) -> int:
    """Build the reconciled inventory equation with backlog kept independent."""
    connection.execute("DROP TABLE IF EXISTS gold_sop_balance")
    connection.execute(
        """
        CREATE TABLE gold_sop_balance AS
        WITH inventory AS (
            SELECT
                site_code,
                product_number,
                CAST(strftime(CAST(position_date AS DATE), '%Y%m') AS INTEGER) AS month_key,
                SUM(beginning_inventory_quantity_ea) AS beginning_inventory_ea,
                SUM(on_hand_quantity_ea) AS ending_inventory_ea,
                SUM(reserved_quantity_ea) AS reserved_inventory_ea,
                SUM(available_quantity_ea) AS available_inventory_ea
            FROM slvr_material_inventory_position
            WHERE is_valid
            GROUP BY ALL
        ),
        production AS (
            SELECT
                site_code,
                product_number,
                month_key,
                planning_version_id,
                plan_as_of_date,
                SUM(constrained_production_quantity_ea) AS constrained_production_ea
            FROM slvr_constrained_production_plan
            WHERE is_valid
            GROUP BY ALL
        ),
        receipts AS (
            SELECT
                site_code,
                product_number,
                CAST(strftime(CAST(expected_receipt_date AS DATE), '%Y%m') AS INTEGER) AS month_key,
                SUM(received_quantity_ea) AS receipt_quantity_ea
            FROM slvr_inbound_receipt
            WHERE is_valid
            GROUP BY ALL
        ),
        shipments AS (
            SELECT
                site_code,
                product_number,
                CAST(strftime(CAST(shipment_date AS DATE), '%Y%m') AS INTEGER) AS month_key,
                SUM(shipped_quantity_ea) AS shipment_quantity_ea
            FROM slvr_shipment
            WHERE is_valid
            GROUP BY ALL
        ),
        orders AS (
            SELECT
                site_code,
                product_number,
                CAST(
                    strftime(CAST(requested_delivery_date AS DATE), '%Y%m') AS INTEGER
                ) AS month_key,
                SUM(ordered_quantity_ea) AS customer_order_quantity_ea
            FROM slvr_customer_order
            WHERE is_valid
            GROUP BY ALL
        ),
        backlog AS (
            SELECT
                site_code,
                product_number,
                CAST(strftime(CAST(position_date AS DATE), '%Y%m') AS INTEGER) AS month_key,
                SUM(open_quantity_ea) AS ending_backlog_ea,
                MAX(backlog_age_days) AS oldest_backlog_days
            FROM slvr_backlog_position
            WHERE is_valid
            GROUP BY ALL
        )
        SELECT
            md5(
                inventory.site_code || '|' || inventory.product_number || '|' ||
                CAST(inventory.month_key AS VARCHAR) || '|' || production.planning_version_id
            ) AS sop_balance_id,
            inventory.site_code,
            inventory.product_number,
            inventory.month_key,
            production.planning_version_id,
            production.plan_as_of_date,
            inventory.beginning_inventory_ea,
            production.constrained_production_ea,
            receipts.receipt_quantity_ea,
            shipments.shipment_quantity_ea,
            inventory.ending_inventory_ea,
            (
                inventory.beginning_inventory_ea
                + production.constrained_production_ea
                + receipts.receipt_quantity_ea
                - shipments.shipment_quantity_ea
            ) AS calculated_ending_inventory_ea,
            inventory.ending_inventory_ea - (
                inventory.beginning_inventory_ea
                + production.constrained_production_ea
                + receipts.receipt_quantity_ea
                - shipments.shipment_quantity_ea
            ) AS inventory_balance_variance_ea,
            inventory.reserved_inventory_ea,
            inventory.available_inventory_ea,
            orders.customer_order_quantity_ea,
            backlog.ending_backlog_ea,
            backlog.oldest_backlog_days,
            safety.safety_stock_quantity_ea,
            safety.coverage_days AS safety_stock_coverage_days,
            service.fill_rate_target_pct,
            service.on_time_in_full_target_pct,
            service.maximum_backlog_days,
            inventory.ending_inventory_ea / NULLIF(shipments.shipment_quantity_ea, 0)
                AS inventory_coverage_months,
            CASE
                WHEN backlog.ending_backlog_ea > 0 THEN 'BACKLOG_RISK'
                WHEN inventory.ending_inventory_ea < safety.safety_stock_quantity_ea
                    THEN 'INVENTORY_RISK'
                ELSE 'ON_TARGET'
            END AS service_risk_status,
            'EA' AS quantity_unit
        FROM inventory
        JOIN production USING (site_code, product_number, month_key)
        JOIN receipts USING (site_code, product_number, month_key)
        JOIN shipments USING (site_code, product_number, month_key)
        JOIN orders USING (site_code, product_number, month_key)
        JOIN backlog USING (site_code, product_number, month_key)
        JOIN slvr_safety_stock_policy safety
          ON inventory.site_code = safety.site_code
         AND inventory.product_number = safety.product_number
        JOIN slvr_service_target service
          ON inventory.site_code = service.site_code
         AND inventory.product_number = service.product_number
        WHERE safety.is_valid AND service.is_valid
        """
    )
    assert_unique_grain(
        connection,
        "gold_sop_balance",
        ["site_code", "product_number", "month_key", "planning_version_id"],
    )
    invalid = connection.execute(
        """
        SELECT COUNT(*) FROM gold_sop_balance
        WHERE ABS(inventory_balance_variance_ea) > 0.000001
           OR ending_inventory_ea < 0
           OR ending_backlog_ea < 0
        """
    ).fetchone()[0]
    if invalid:
        raise ValueError(f"S&OP balance contains {invalid} invalid reconciliations")
    return int(connection.execute("SELECT COUNT(*) FROM gold_sop_balance").fetchone()[0])


def build_npi_planning(connection) -> dict[str, int]:
    """Build one readiness record per program and one target/actual ramp series."""
    connection.execute("DROP TABLE IF EXISTS gold_npi_readiness")
    connection.execute(
        """
        CREATE TABLE gold_npi_readiness AS
        WITH gates AS (
            SELECT program_id,
                   COUNT(*) AS gate_count,
                   SUM(CASE WHEN gate_status = 'PASSED' THEN 1 ELSE 0 END) AS gates_passed
            FROM slvr_npi_stage_gate WHERE is_valid GROUP BY program_id
        ),
        milestones AS (
            SELECT program_id,
                   COUNT(*) AS milestone_count,
                   SUM(CASE WHEN milestone_status = 'COMPLETE' THEN 1 ELSE 0 END)
                       AS milestones_complete
            FROM slvr_npi_milestone WHERE is_valid GROUP BY program_id
        ),
        qualification AS (
            SELECT program_id,
                   COUNT(*) AS qualification_count,
                   SUM(CASE WHEN result_status = 'ACCEPTED' THEN 1 ELSE 0 END)
                       AS qualifications_accepted
            FROM slvr_npi_qualification_evidence WHERE is_valid GROUP BY program_id
        ),
        tooling AS (
            SELECT program_id,
                   AVG(readiness_pct) AS tooling_readiness_pct,
                   SUM(CASE WHEN readiness_status = 'AT_RISK' THEN 1 ELSE 0 END)
                       AS tooling_items_at_risk
            FROM slvr_npi_tooling_readiness WHERE is_valid GROUP BY program_id
        ),
        pilot AS (
            SELECT program_id,
                   COUNT(*) AS pilot_lot_count,
                   SUM(started_quantity_ea) AS pilot_started_quantity_ea,
                   SUM(passed_quantity_ea) AS pilot_passed_quantity_ea,
                   SUM(passed_quantity_ea) / NULLIF(SUM(started_quantity_ea), 0)
                       AS pilot_yield_pct
            FROM slvr_npi_pilot_lot WHERE is_valid GROUP BY program_id
        ),
        risks AS (
            SELECT program_id,
                   COUNT(*) FILTER (WHERE risk_status = 'OPEN') AS open_risk_count,
                   MAX(probability_pct * impact_score) AS maximum_risk_score
            FROM slvr_npi_risk WHERE is_valid GROUP BY program_id
        ),
        owners AS (
            SELECT program_id, COUNT(DISTINCT owner_role) AS active_owner_count
            FROM slvr_npi_owner
            WHERE is_valid AND owner_status = 'ACTIVE'
            GROUP BY program_id
        )
        SELECT
            program.program_id,
            program.program_name,
            program.product_number,
            program.lead_site_code,
            program.planned_launch_date,
            program.program_status,
            gates.gate_count,
            gates.gates_passed,
            milestones.milestone_count,
            milestones.milestones_complete,
            qualification.qualification_count,
            qualification.qualifications_accepted,
            tooling.tooling_readiness_pct,
            tooling.tooling_items_at_risk,
            pilot.pilot_lot_count,
            pilot.pilot_started_quantity_ea,
            pilot.pilot_passed_quantity_ea,
            pilot.pilot_yield_pct,
            risks.open_risk_count,
            risks.maximum_risk_score,
            owners.active_owner_count,
            ROUND(
                (
                    gates.gates_passed / NULLIF(gates.gate_count, 0)
                    + milestones.milestones_complete / NULLIF(milestones.milestone_count, 0)
                    + qualification.qualifications_accepted
                        / NULLIF(qualification.qualification_count, 0)
                    + tooling.tooling_readiness_pct
                    + pilot.pilot_yield_pct
                ) / 5.0,
                4
            ) AS readiness_score_pct,
            CASE
                WHEN risks.open_risk_count > 0 AND risks.maximum_risk_score >= 1.5
                    THEN 'HIGH'
                WHEN tooling.tooling_items_at_risk > 0 THEN 'MEDIUM'
                ELSE 'LOW'
            END AS launch_risk_tier,
            'PCT' AS ratio_unit
        FROM slvr_npi_program program
        JOIN gates USING (program_id)
        JOIN milestones USING (program_id)
        JOIN qualification USING (program_id)
        JOIN tooling USING (program_id)
        JOIN pilot USING (program_id)
        JOIN risks USING (program_id)
        JOIN owners USING (program_id)
        WHERE program.is_valid
        """
    )
    connection.execute("DROP TABLE IF EXISTS gold_npi_ramp")
    connection.execute(
        """
        CREATE TABLE gold_npi_ramp AS
        SELECT
            target.program_id,
            program.product_number,
            target.site_code,
            target.month_key,
            target.target_quantity_ea,
            actual.actual_quantity_ea,
            actual.cumulative_quantity_ea,
            target.target_yield_pct,
            actual.actual_yield_pct,
            actual.actual_quantity_ea - target.target_quantity_ea AS ramp_quantity_variance_ea,
            actual.actual_yield_pct - target.target_yield_pct AS ramp_yield_variance_pct,
            target.target_status,
            actual.actual_status,
            'EA' AS quantity_unit,
            'PCT' AS ratio_unit
        FROM slvr_npi_ramp_target target
        JOIN slvr_npi_program program USING (program_id)
        LEFT JOIN slvr_npi_ramp_actual actual
          ON target.program_id = actual.program_id
         AND target.site_code = actual.site_code
         AND target.month_key = actual.month_key
        WHERE target.is_valid AND program.is_valid
        """
    )
    assert_unique_grain(connection, "gold_npi_readiness", ["program_id"])
    assert_unique_grain(connection, "gold_npi_ramp", ["program_id", "site_code", "month_key"])
    return {
        "gold_npi_readiness": int(
            connection.execute("SELECT COUNT(*) FROM gold_npi_readiness").fetchone()[0]
        ),
        "gold_npi_ramp": int(
            connection.execute("SELECT COUNT(*) FROM gold_npi_ramp").fetchone()[0]
        ),
    }


def build_operations_flow(connection) -> dict[str, int]:
    """Build bounded event-derived operations measures."""
    connection.execute("DROP TABLE IF EXISTS gold_operations_event")
    connection.execute(
        """
        CREATE TABLE gold_operations_event AS
        SELECT
            *,
            date_diff(
                'minute',
                CAST(queue_entry_at AS TIMESTAMP),
                CAST(queue_exit_at AS TIMESTAMP)
            ) AS queue_age_minutes,
            date_diff(
                'minute',
                CAST(queue_exit_at AS TIMESTAMP),
                CAST(movement_event_at AS TIMESTAMP)
            ) AS processing_minutes,
            CAST(CAST(movement_event_at AS TIMESTAMP) AS DATE) AS movement_date
        FROM slvr_lot_route_movement_event
        WHERE is_valid
        """
    )
    connection.execute("DROP TABLE IF EXISTS gold_operations_wip")
    connection.execute(
        """
        CREATE TABLE gold_operations_wip AS
        WITH latest AS (
            SELECT event.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY event.work_order_id
                       ORDER BY CAST(event.movement_event_at AS TIMESTAMP) DESC
                   ) AS recency
            FROM gold_operations_event event
            JOIN slvr_production_schedule schedule USING (work_order_id)
            WHERE schedule.schedule_status = 'IN_PROGRESS'
        )
        SELECT
            site_code,
            product_number,
            to_operation AS current_operation,
            resource_id,
            COUNT(DISTINCT work_order_id) AS work_order_count,
            COUNT(DISTINCT lot_id) AS lot_count,
            SUM(output_quantity_ea) AS wip_quantity_ea,
            MAX(queue_age_minutes) AS maximum_queue_age_minutes,
            'EA' AS quantity_unit,
            'MIN' AS age_unit
        FROM latest
        WHERE recency = 1
        GROUP BY ALL
        """
    )
    connection.execute("DROP TABLE IF EXISTS gold_operations_queue")
    connection.execute(
        """
        CREATE TABLE gold_operations_queue AS
        SELECT
            movement_date,
            site_code,
            to_operation AS operation,
            resource_id,
            COUNT(*) AS lot_count,
            SUM(input_quantity_ea) AS queued_quantity_ea,
            AVG(queue_age_minutes) AS average_queue_age_minutes,
            quantile_cont(queue_age_minutes, 0.5) AS p50_queue_age_minutes,
            quantile_cont(queue_age_minutes, 0.9) AS p90_queue_age_minutes,
            MAX(queue_age_minutes) AS maximum_queue_age_minutes,
            'EA' AS quantity_unit,
            'MIN' AS age_unit
        FROM gold_operations_event
        GROUP BY ALL
        """
    )
    connection.execute("DROP TABLE IF EXISTS gold_operations_cycle_time")
    connection.execute(
        """
        CREATE TABLE gold_operations_cycle_time AS
        WITH lot_cycle AS (
            SELECT
                CAST(MIN(CAST(queue_entry_at AS TIMESTAMP)) AS DATE) AS release_date,
                site_code,
                product_number,
                work_order_id,
                lot_id,
                date_diff(
                    'minute',
                    MIN(CAST(queue_entry_at AS TIMESTAMP)),
                    MAX(CAST(movement_event_at AS TIMESTAMP))
                ) AS cycle_time_minutes
            FROM gold_operations_event
            GROUP BY site_code, product_number, work_order_id, lot_id
        )
        SELECT
            release_date,
            site_code,
            product_number,
            COUNT(*) AS completed_lot_count,
            AVG(cycle_time_minutes) AS average_cycle_time_minutes,
            quantile_cont(cycle_time_minutes, 0.5) AS p50_cycle_time_minutes,
            quantile_cont(cycle_time_minutes, 0.9) AS p90_cycle_time_minutes,
            'MIN' AS time_unit
        FROM lot_cycle
        GROUP BY ALL
        """
    )
    connection.execute("DROP TABLE IF EXISTS gold_operations_throughput")
    connection.execute(
        """
        CREATE TABLE gold_operations_throughput AS
        SELECT
            movement_date,
            site_code,
            to_operation AS operation,
            resource_id,
            COUNT(DISTINCT lot_id) AS processed_lot_count,
            SUM(output_quantity_ea) AS throughput_quantity_ea,
            SUM(output_quantity_ea) / NULLIF(SUM(processing_minutes) / 60.0, 0)
                AS throughput_quantity_per_hour,
            'EA' AS quantity_unit,
            'EA_PER_HR' AS rate_unit
        FROM gold_operations_event
        GROUP BY ALL
        """
    )
    connection.execute("DROP TABLE IF EXISTS gold_operations_rework")
    connection.execute(
        """
        CREATE TABLE gold_operations_rework AS
        SELECT
            movement_date,
            site_code,
            product_number,
            to_operation AS operation,
            COUNT(*) AS movement_count,
            COUNT(*) FILTER (WHERE disposition_code = 'REWORK') AS rework_count,
            COUNT(*) FILTER (WHERE disposition_code = 'SCRAP') AS scrap_count,
            COUNT(*) FILTER (WHERE disposition_code = 'REWORK')
                / NULLIF(COUNT(*), 0) AS rework_rate_pct,
            'PCT' AS ratio_unit
        FROM gold_operations_event
        GROUP BY ALL
        """
    )
    connection.execute("DROP TABLE IF EXISTS gold_operations_route_adherence")
    connection.execute(
        """
        CREATE TABLE gold_operations_route_adherence AS
        WITH expected AS (
            SELECT route_id, COUNT(*) AS expected_step_count
            FROM slvr_route_step
            WHERE is_valid
            GROUP BY route_id
        ),
        observed AS (
            SELECT
                site_code,
                product_number,
                work_order_id,
                lot_id,
                route_id,
                COUNT(DISTINCT route_step_id) AS observed_step_count,
                MAX(route_step_sequence) AS maximum_step_sequence
            FROM gold_operations_event
            GROUP BY ALL
        )
        SELECT
            observed.*,
            expected.expected_step_count,
            observed.observed_step_count = expected.expected_step_count
                AND observed.maximum_step_sequence = expected.expected_step_count
                AS route_adherent
        FROM observed
        JOIN expected USING (route_id)
        """
    )
    connection.execute("DROP TABLE IF EXISTS gold_operations_schedule_attainment")
    connection.execute(
        """
        CREATE TABLE gold_operations_schedule_attainment AS
        SELECT
            CAST(CAST(scheduled_complete_at AS TIMESTAMP) AS DATE) AS schedule_date,
            site_code,
            product_number,
            COUNT(*) AS scheduled_work_order_count,
            COUNT(*) FILTER (
                WHERE schedule_status = 'COMPLETE'
                  AND CAST(actual_complete_at AS TIMESTAMP)
                      <= CAST(scheduled_complete_at AS TIMESTAMP)
            ) AS attained_work_order_count,
            SUM(planned_quantity_ea) AS planned_quantity_ea,
            SUM(completed_quantity_ea) AS completed_quantity_ea,
            COUNT(*) FILTER (
                WHERE schedule_status = 'COMPLETE'
                  AND CAST(actual_complete_at AS TIMESTAMP)
                      <= CAST(scheduled_complete_at AS TIMESTAMP)
            ) / NULLIF(COUNT(*), 0) AS schedule_attainment_pct,
            'EA' AS quantity_unit,
            'PCT' AS ratio_unit
        FROM slvr_production_schedule
        WHERE is_valid
        GROUP BY ALL
        """
    )
    connection.execute("DROP TABLE IF EXISTS gold_operations_bottleneck_movement")
    connection.execute(
        """
        CREATE TABLE gold_operations_bottleneck_movement AS
        WITH ranked AS (
            SELECT
                movement_date,
                site_code,
                operation,
                resource_id,
                p90_queue_age_minutes,
                ROW_NUMBER() OVER (
                    PARTITION BY movement_date, site_code
                    ORDER BY p90_queue_age_minutes DESC, operation, resource_id
                ) AS severity_rank
            FROM gold_operations_queue
        ),
        daily AS (
            SELECT * FROM ranked WHERE severity_rank = 1
        )
        SELECT
            *,
            LAG(operation) OVER (
                PARTITION BY site_code ORDER BY movement_date
            ) AS prior_bottleneck_operation,
            operation != LAG(operation) OVER (
                PARTITION BY site_code ORDER BY movement_date
            ) AS bottleneck_moved,
            'MIN' AS age_unit
        FROM daily
        """
    )
    tables = (
        "gold_operations_event",
        "gold_operations_wip",
        "gold_operations_queue",
        "gold_operations_cycle_time",
        "gold_operations_throughput",
        "gold_operations_rework",
        "gold_operations_route_adherence",
        "gold_operations_schedule_attainment",
        "gold_operations_bottleneck_movement",
    )
    return {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in tables
    }


def build_scenario_inputs(connection) -> dict[str, int]:
    """Publish governed baseline values; scenario changes remain client-session only."""
    connection.execute("DROP TABLE IF EXISTS gold_equipment_cost_reference")
    connection.execute(
        """
        CREATE TABLE gold_equipment_cost_reference AS
        SELECT
            equipment_cost_reference_id,
            equipment_id,
            effective_start_date,
            effective_end_date,
            purchase_cost_usd,
            annual_maintenance_cost_usd,
            installation_cost_usd,
            lead_time_days,
            currency_code,
            cost_status
        FROM slvr_equipment_cost_reference
        WHERE is_valid
        """
    )
    connection.execute("DROP TABLE IF EXISTS gold_scenario_inputs")
    connection.execute(
        """
        CREATE TABLE gold_scenario_inputs AS
        SELECT
            'DEMAND' AS assumption_type,
            site_code,
            product_number,
            month_key,
            NULL::VARCHAR AS resource_id,
            planning_version_id,
            plan_as_of_date,
            customer_order_quantity_ea AS baseline_value,
            'EA' AS unit_code,
            0.70 * customer_order_quantity_ea AS lower_bound,
            1.30 * customer_order_quantity_ea AS upper_bound,
            'gold_sop_balance.customer_order_quantity_ea' AS source_field
        FROM gold_sop_balance
        UNION ALL
        SELECT
            'SERVICE_TARGET',
            site_code,
            product_number,
            month_key,
            NULL::VARCHAR,
            planning_version_id,
            plan_as_of_date,
            fill_rate_target_pct,
            'PCT',
            0.80,
            1.00,
            'gold_sop_balance.fill_rate_target_pct'
        FROM gold_sop_balance
        UNION ALL
        SELECT
            'SHARED_RESOURCE_HOURS',
            site_code,
            product_number,
            month_key,
            resource_id,
            planning_version_id,
            plan_as_of_date,
            allocated_resource_hours,
            'HR',
            0.0,
            2.0 * allocated_resource_hours,
            'slvr_shared_resource_allocation.allocated_resource_hours'
        FROM slvr_shared_resource_allocation
        WHERE is_valid
        """
    )
    return {
        "gold_equipment_cost_reference": int(
            connection.execute("SELECT COUNT(*) FROM gold_equipment_cost_reference").fetchone()[0]
        ),
        "gold_scenario_inputs": int(
            connection.execute("SELECT COUNT(*) FROM gold_scenario_inputs").fetchone()[0]
        ),
    }


def build_planning_foundation(connection) -> dict[str, int]:
    """Build and validate all Phase 6 Gold datasets."""
    counts = {"gold_sop_balance": build_sop_balance(connection)}
    counts.update(build_npi_planning(connection))
    counts.update(build_operations_flow(connection))
    counts.update(build_scenario_inputs(connection))
    return counts
