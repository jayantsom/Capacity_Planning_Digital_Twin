"""Checks for shared date and threshold contracts."""

from capacity_twin_core.domain import constants


def test_actual_and_forecast_ranges_are_contiguous() -> None:
    """Keep the agreed execution and forecast boundary explicit."""
    assert constants.ACTUAL_START == "2023-01-01"
    assert constants.ACTUAL_END == "2026-10-31"
    assert constants.FORECAST_START == "2026-11-01"
    assert constants.FORECAST_END == "2027-12-31"


def test_bottleneck_thresholds_use_signed_gap_ratios() -> None:
    """Shortages are negative and excess capacity is positive."""
    assert constants.THRESHOLD_CRITICAL == -0.15
    assert constants.THRESHOLD_HIGH == -0.08
    assert constants.THRESHOLD_MEDIUM == -0.03
    assert constants.THRESHOLD_BALANCED == 0.05
