"""Contracts for honest weekly and monthly operational analytics."""

import duckdb

from data_operations.pipeline.pipeline.gold.analytics import (
    build_operational_time_grains,
)


def test_operational_rollups_conserve_quantities_and_recompute_rates() -> None:
    """Weekly and monthly totals must come from the same daily facts."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE slvr_machine_execution AS
        SELECT * FROM (
            VALUES
                ('F1', 'S1', 'P1', 'ICT', DATE '2026-01-05',
                 90.0, 10.0, 100.0, 30.0, 5.0, 10.0, 60.0, 12.0, 'run-1', true),
                ('F1', 'S1', 'P1', 'ICT', DATE '2026-01-06',
                 80.0, 20.0, 100.0, 30.0, 5.0, 10.0, 120.0, 10.0, 'run-1', true)
        ) AS source(
            factory_code, site_code, product_number, test_type, execution_date,
            passed_qty_sum, failed_qty_sum, total_qty_sum, test_duration_avg,
            handling_time_avg, idle_time_avg, equipment_downtime_avg,
            actual_throughput, pipeline_run_id, is_valid
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE slvr_machine_test_param AS
        SELECT * FROM (
            VALUES
                ('F1', 'S1', 'P1', 'ICT', DATE '2026-01-05',
                 85.0, 15.0, true),
                ('F1', 'S1', 'P1', 'ICT', DATE '2026-01-06',
                 75.0, 25.0, true)
        ) AS source(
            factory_code, site_code, product_number, test_type, execution_date,
            first_pass_qty_sum, first_fail_qty_sum, is_valid
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE slvr_machine_logs AS
        SELECT 'F1' AS factory_code, 'S1' AS site_code, 'P1' AS product_number,
               'ICT' AS test_type, DATE '2026-01-05' AS execution_date,
               'WARN' AS severity, 'W-001' AS error_code,
               'run-1' AS pipeline_run_id, true AS is_valid
        """
    )

    counts = build_operational_time_grains(connection)
    weekly = connection.execute(
        """
        SELECT tested_qty, passed_qty, yield_pct, first_pass_yield_pct
        FROM gold_operational_performance
        WHERE period_grain = 'WEEK'
        """
    ).fetchone()
    monthly = connection.execute(
        """
        SELECT tested_qty, passed_qty
        FROM gold_operational_performance
        WHERE period_grain = 'MONTH'
        """
    ).fetchone()

    assert counts == {
        "gold_operational_performance": 2,
        "gold_operational_events": 2,
    }
    assert weekly[:2] == monthly == (200.0, 170.0)
    assert weekly[2] == 0.85
    assert weekly[3] == 0.8
