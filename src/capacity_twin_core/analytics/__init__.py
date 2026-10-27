"""Shared analytical aggregation contracts."""

from capacity_twin_core.analytics.time_grain import (
    MeasureRule,
    TimeGrain,
    supported_grains,
)

__all__ = ["MeasureRule", "TimeGrain", "supported_grains"]
