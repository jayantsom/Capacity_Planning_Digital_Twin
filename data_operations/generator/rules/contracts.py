"""Typed generator rules loaded from the app-owned configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

DEMAND_CLASSES = ("DIRECT_CUSTOMER", "SPARE", "SERVICE", "BOM_DEPENDENT")
INDEPENDENT_DEMAND_CLASSES = ("DIRECT_CUSTOMER", "SPARE", "SERVICE")
RESOURCE_SCENARIOS = (
    "ALTERNATIVE_POOL",
    "SERIAL_STEP",
    "PAIRED_FIXTURE",
    "MULTI_DUT",
    "STANDALONE",
    "SHARED_POOL",
    "DEDICATED",
)


@dataclass(frozen=True)
class DateContract:
    """Inclusive actual and forecast boundaries."""

    actual_start: date
    actual_end: date
    forecast_start: date
    forecast_end: date
    snapshot_dates: tuple[date, ...]

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> DateContract:
        """Parse and validate configured ISO dates."""
        values = config["data_generation"]
        contract = cls(
            actual_start=date.fromisoformat(values["start_date_actual"]),
            actual_end=date.fromisoformat(values["end_date_actual"]),
            forecast_start=date.fromisoformat(values["start_date_forecast"]),
            forecast_end=date.fromisoformat(values["end_date_forecast"]),
            snapshot_dates=tuple(date.fromisoformat(item) for item in values["snapshot_dates"]),
        )
        if contract.actual_start > contract.actual_end:
            raise ValueError("Actual start must not be after actual end")
        if contract.forecast_start != date.fromordinal(contract.actual_end.toordinal() + 1):
            raise ValueError("Forecast must begin on the day after the actual cutoff")
        if contract.forecast_start > contract.forecast_end:
            raise ValueError("Forecast start must not be after forecast end")
        if tuple(sorted(contract.snapshot_dates)) != contract.snapshot_dates:
            raise ValueError("Snapshot dates must be ordered")
        if contract.snapshot_dates[-1] != contract.actual_end:
            raise ValueError("The latest snapshot must equal the actual cutoff")
        return contract


@dataclass(frozen=True)
class VolumeContract:
    """Density settings for low, medium, or high local generation."""

    name: str
    execution_day_stride: int
    demand_scale: float
    log_probability_scale: float

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> VolumeContract:
        """Load the selected volume without changing date boundaries."""
        name = str(config["data_generation"]["volume"]).lower()
        values = config["volume_profiles"][name]
        contract = cls(name=name, **values)
        if contract.execution_day_stride < 1:
            raise ValueError("Execution day stride must be at least one")
        if not 0 < contract.demand_scale <= 1:
            raise ValueError("Demand scale must be in (0, 1]")
        if not 0 < contract.log_probability_scale <= 1:
            raise ValueError("Log probability scale must be in (0, 1]")
        return contract
