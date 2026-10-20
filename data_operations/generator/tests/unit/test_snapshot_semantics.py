"""Planning snapshots keep known history stable and future values honest."""

import numpy as np

from capacity_twin_core.dates.months import month_key_label
from data_operations.generator.generators.demand_forecast import generate_demand_for_snapshot


def test_historical_actuals_do_not_change_between_snapshots() -> None:
    months = [202510, 202511, 202610, 202611]
    early = generate_demand_for_snapshot(
        "snap-2025-10-31",
        "2025-10-31",
        months,
        np.random.default_rng(42),
        42,
    )
    current = generate_demand_for_snapshot(
        "snap-2026-10-31",
        "2026-10-31",
        months,
        np.random.default_rng(42),
        42,
    )
    key = ["site", "product_number"]
    joined = early.merge(current, on=key, suffixes=("_early", "_current"))
    assert (
        joined[f"{month_key_label(202510)}_early"]
        == joined[f"{month_key_label(202510)}_current"]
    ).all()
