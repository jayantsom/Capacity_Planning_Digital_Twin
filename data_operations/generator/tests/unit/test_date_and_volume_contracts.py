"""Configuration checks for exact horizons and bounded volume profiles."""

from datetime import date

from capacity_twin_core.runtime.database_paths import load_config
from data_operations.generator.rules.contracts import DateContract, VolumeContract


def test_exact_actual_and_forecast_boundaries() -> None:
    dates = DateContract.from_config(load_config())
    assert dates.actual_start == date(2023, 1, 1)
    assert dates.actual_end == date(2026, 10, 31)
    assert dates.forecast_start == date(2026, 11, 1)
    assert dates.forecast_end == date(2027, 12, 31)


def test_low_medium_and_high_volumes_are_valid() -> None:
    config = load_config()
    for name in ("low", "medium", "high"):
        config["data_generation"]["volume"] = name
        assert VolumeContract.from_config(config).name == name
