"""Golden tests for shared capacity and OEE formulas."""

import pytest

from capacity_twin_core.capacity.formulas import (
    ResourceBehavior,
    calculate_effective_parallel_duts,
    calculate_oee,
    calculate_scenario_gap,
    classify_bottleneck,
)
from data_operations.pipeline.pipeline.gold.capacity_math import capacity_steps


@pytest.mark.parametrize(
    ("gap_ratio", "expected"),
    [
        (-0.16, "CRITICAL"),
        (-0.15, "HIGH"),
        (-0.08, "MEDIUM"),
        (-0.03, "LOW"),
        (0.00, "BALANCED"),
        (0.05, "BALANCED"),
        (0.051, "EXCESS"),
    ],
)
def test_bottleneck_threshold_boundaries(gap_ratio: float, expected: str) -> None:
    """Keep detail and aggregate severity boundaries identical."""
    assert classify_bottleneck(gap_ratio) == expected


def test_capacity_steps_match_hand_calculated_case() -> None:
    """Check one simple monthly equipment-capacity example."""
    result = capacity_steps(
        handling_time_sec=0,
        target_test_time_sec=60,
        target_yield=0.99,
        retest_times=0,
        test_x_parameter=0,
        utilization_rate=1,
        hours_per_shift=8,
        allowance_pct=0,
        productivity_pct=1,
        working_days=20,
        shifts_per_day=1,
        equip_qty=1,
        demand_qty=14_400,
    )

    assert result["step3_productivity_adjusted"] == pytest.approx(480.0)
    assert result["capacity_qty"] == pytest.approx(9_600.0)
    assert result["gap_pct"] == pytest.approx(-1 / 3, abs=0.0001)
    assert result["investment_need_units"] == 1
    assert result["bottleneck_severity"] == "CRITICAL"


def test_oee_is_component_product() -> None:
    """Calculate OEE from compatible ratio units."""
    assert calculate_oee(0.90, 0.80, 0.95) == pytest.approx(0.684)


def test_multi_dut_capacity_uses_smallest_constraint() -> None:
    """Limit multi-DUT capacity by hardware, fixture, handler, and licence."""
    result = calculate_effective_parallel_duts(
        tester_channels=16,
        licensed_ports=8,
        fixture_cavities=4,
        handler_sockets=6,
        parallel_efficiency=0.85,
    )

    assert result == pytest.approx(3.4)


@pytest.mark.parametrize(
    ("behavior", "demands", "capacities", "factor", "expected"),
    [
        (ResourceBehavior.ALTERNATIVE_POOL, [100], [60, 50], 1.0, (100, 110, 10)),
        (ResourceBehavior.SERIAL_STEP, [100], [120, 90], 1.0, (100, 90, -10)),
        (ResourceBehavior.PAIRED_FIXTURE, [100], [120, 80], 1.0, (100, 80, -20)),
        (ResourceBehavior.MULTI_DUT, [100], [30], 3.4, (100, 102, 2)),
        (ResourceBehavior.STANDALONE, [100], [105], 1.0, (100, 105, 5)),
        (ResourceBehavior.SHARED_POOL, [60, 50], [100], 1.0, (110, 100, -10)),
        (ResourceBehavior.DEDICATED, [100], [95], 1.0, (100, 95, -5)),
    ],
)
def test_resource_behavior_golden_cases(
    behavior: ResourceBehavior,
    demands: list[float],
    capacities: list[float],
    factor: float,
    expected: tuple[float, float, float],
) -> None:
    """Freeze one hand-calculated example for every resource behavior."""
    assert calculate_scenario_gap(
        behavior,
        demands,
        capacities,
        multi_dut_factor=factor,
    ) == pytest.approx(expected)
