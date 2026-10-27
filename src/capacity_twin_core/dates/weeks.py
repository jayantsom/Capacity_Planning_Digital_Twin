"""ISO-week helpers shared by APIs, pipelines, and tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class IsoWeek:
    """One Monday-to-Sunday ISO week."""

    key: str
    start: date
    end: date


def iso_week(value: date) -> IsoWeek:
    """Return the ISO week containing a date."""
    year, week, _ = value.isocalendar()
    start = value - timedelta(days=value.weekday())
    return IsoWeek(f"{year:04d}-W{week:02d}", start, start + timedelta(days=6))


def is_partial_week(start_date: date, end_date: date, week: IsoWeek) -> bool:
    """Return whether a selected range cuts either side of the ISO week."""
    return start_date > week.start or end_date < week.end
