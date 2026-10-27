"""Comparison-window contracts are independent from planning versions."""

from datetime import date

import pytest

from capacity_twin_core.comparison.windows import (
    ComparisonWindow,
    get_comparison_window,
    resolve_time_column,
    window_predicate,
)


def test_total_window_does_not_require_a_control_publication(tmp_path) -> None:
    """TOTAL is always a safe full-range selection."""
    window = get_comparison_window("total", tmp_path)
    assert window.window_id == "total"
    assert window_predicate(window, "month_key", "month_key") == ("", [])


def test_snapshots_use_inclusive_date_and_month_bounds() -> None:
    """The same ISO dates map cleanly to date and monthly datasets."""
    window = ComparisonWindow(
        "band_1",
        "Snapshot 1",
        date(2023, 1, 15),
        date(2024, 12, 20),
        1,
    )
    assert window_predicate(window, "execution_date", "date")[1] == [
        "2023-01-15",
        "2024-12-20",
    ]
    assert window_predicate(window, "month_key", "month_key")[1] == [
        202301,
        202412,
    ]


def test_time_column_mapping_prefers_daily_facts() -> None:
    """Daily facts take precedence when a table also carries a month key."""
    assert resolve_time_column({"execution_date", "month_key"}) == (
        "execution_date",
        "date",
    )
    with pytest.raises(ValueError):
        window_predicate(
            ComparisonWindow("band_1", "Snapshot 1", date.today(), date.today(), 1),
            "value",
            "unsupported",  # type: ignore[arg-type]
        )
