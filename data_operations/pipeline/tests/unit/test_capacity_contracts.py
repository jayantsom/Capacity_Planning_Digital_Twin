"""Capacity tests owned by the app that publishes Gold facts."""

import duckdb
import pytest

from capacity_twin_core.capacity.formulas import ResourceBehavior
from data_operations.pipeline.pipeline.gold.capacity_math import (
    build_resource_scenario_table,
    capacity_steps,
    resource_scenario_summary,
)


def test_multi_dut_factor_changes_supply_and_equipment_need() -> None:
    """Measured parallel DUT throughput must affect both capacity and need."""
    result = capacity_steps(
        handling_time_sec=0,
        target_test_time_sec=60,
        target_yield=1,
        retest_times=0,
        test_x_parameter=0,
        utilization_rate=1,
        hours_per_shift=8,
        allowance_pct=0,
        productivity_pct=1,
        working_days=20,
        shifts_per_day=1,
        equip_qty=1,
        demand_qty=19_200,
        parallel_dut_factor=2,
    )

    assert result["capacity_qty"] == pytest.approx(19_200)
    assert result["need_ceiling"] == 1
    assert result["investment_need_units"] == 0


def test_shared_pool_counts_fleet_once() -> None:
    """Compare summed product demand with one pooled fleet supply."""
    result = resource_scenario_summary(
        ResourceBehavior.SHARED_POOL,
        [60, 50],
        [100],
    )

    assert result["demand_qty"] == 110
    assert result["capacity_qty"] == 100
    assert result["gap_qty"] == -10
    assert result["bottleneck_severity"] == "HIGH"


def test_resource_scenario_table_handles_paired_alternative_and_shared_resources() -> None:
    """Aggregate each equipment relationship at its correct planning grain."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE gold_cap_normal (
            site_code VARCHAR,
            month_key INTEGER,
            snapshot_id VARCHAR,
            product_number VARCHAR,
            test_type VARCHAR,
            equipment_id VARCHAR,
            equipment_type VARCHAR,
            capacity_mode VARCHAR,
            retest_type VARCHAR,
            resource_behavior VARCHAR,
            effective_demand_qty DOUBLE,
            capacity_qty DOUBLE
        )
        """
    )
    rows = [
        ("S", 202611, "snap", "P1", "RF", "SYS-1", "SYSTEM",
         "NORMAL", "TYPE1", "DEDICATED", 60, 100),
        ("S", 202611, "snap", "P1", "RF", "FIX-1", "FIXTURE",
         "NORMAL", "TYPE1", "DEDICATED", 60, 80),
        ("S", 202611, "snap", "P2", "ICT", "ICT-1", "SYSTEM",
         "NORMAL", "TYPE1", "DEDICATED", 100, 70),
        ("S", 202611, "snap", "P2", "ICT", "ICT-2", "SYSTEM",
         "NORMAL", "TYPE1", "DEDICATED", 100, 50),
        ("S", 202611, "snap", "P3", "OTA", "OTA-1", "SYSTEM",
         "NORMAL", "TYPE1", "SHARED_POOL", 60, 100),
        ("S", 202611, "snap", "P4", "OTA", "OTA-1", "SYSTEM",
         "NORMAL", "TYPE1", "SHARED_POOL", 50, 100),
    ]
    connection.executemany(
        "INSERT INTO gold_cap_normal VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.execute(
        "CREATE TABLE gold_cap_maximum AS "
        "SELECT * FROM gold_cap_normal WHERE false"
    )

    assert build_resource_scenario_table(connection) == 3
    results = {
        row[0]: row[1:]
        for row in connection.execute(
            """
            SELECT COALESCE(product_number, 'SHARED'), resource_behavior,
                   demand_qty, capacity_qty, gap_qty, affected_products
            FROM gold_resource_scenarios
            ORDER BY 1
            """
        ).fetchall()
    }
    connection.close()

    assert results["P1"] == ("PAIRED_FIXTURE", 60, 80, 20, 1)
    assert results["P2"] == ("ALTERNATIVE_POOL", 100, 120, 20, 1)
    assert results["SHARED"] == ("SHARED_POOL", 110, 100, -10, 2)
