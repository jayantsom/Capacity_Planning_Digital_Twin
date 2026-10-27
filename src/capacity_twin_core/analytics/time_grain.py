"""Declare truthful time-grain support and measure aggregation rules."""

from __future__ import annotations

from enum import StrEnum


class TimeGrain(StrEnum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    NONE = "NONE"


class MeasureRule(StrEnum):
    SUM = "SUM"
    COUNT = "COUNT"
    WEIGHTED_AVERAGE = "WEIGHTED_AVERAGE"
    RECOMPUTED_RATE = "RECOMPUTED_RATE"


def supported_grains(native_grain: TimeGrain) -> tuple[TimeGrain, ...]:
    """Prevent monthly or atemporal data from pretending to be weekly."""
    if native_grain == TimeGrain.DAY:
        return (TimeGrain.DAY, TimeGrain.WEEK, TimeGrain.MONTH)
    if native_grain == TimeGrain.WEEK:
        return (TimeGrain.WEEK, TimeGrain.MONTH)
    if native_grain == TimeGrain.MONTH:
        return (TimeGrain.MONTH,)
    return (TimeGrain.NONE,)
