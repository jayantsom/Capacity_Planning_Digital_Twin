"""Small golden examples for all seven resource behaviors."""

import pytest

from capacity_twin_core.capacity.formulas import ResourceBehavior, calculate_scenario_gap


@pytest.mark.parametrize(
    ("behavior", "demands", "capacities", "factor", "expected"),
    [
        (ResourceBehavior.ALTERNATIVE_POOL, [100], [60, 50], 1.0, (100, 110, 10)),
        (ResourceBehavior.SERIAL_STEP, [100], [120, 90], 1.0, (100, 90, -10)),
        (ResourceBehavior.PAIRED_FIXTURE, [100], [110, 80], 1.0, (100, 80, -20)),
        (ResourceBehavior.MULTI_DUT, [100], [25], 4.0, (100, 100, 0)),
        (ResourceBehavior.STANDALONE, [100], [105], 1.0, (100, 105, 5)),
        (ResourceBehavior.SHARED_POOL, [60, 50], [100], 1.0, (110, 100, -10)),
        (ResourceBehavior.DEDICATED, [100], [95], 1.0, (100, 95, -5)),
    ],
)
def test_capacity_behavior_golden_examples(
    behavior: ResourceBehavior,
    demands: list[float],
    capacities: list[float],
    factor: float,
    expected: tuple[float, float, float],
) -> None:
    assert calculate_scenario_gap(
        behavior, demands, capacities, multi_dut_factor=factor
    ) == expected
