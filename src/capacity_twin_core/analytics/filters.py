"""Dataset-owned filter declarations for shared dashboards."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from capacity_twin_core.analytics.time_grain import TimeGrain


@dataclass(frozen=True, slots=True)
class FilterContract:
    """Declare filters and grains supported by one server dataset."""

    dataset_id: str
    filters: frozenset[str]
    grains: tuple[TimeGrain, ...]

    def validate(self, submitted: Mapping[str, object]) -> dict[str, object]:
        """Return supplied supported values and reject unsupported controls."""
        supplied = {
            key: value for key, value in submitted.items() if value not in (None, "", [])
        }
        unsupported = sorted(set(supplied) - self.filters)
        if unsupported:
            raise ValueError(
                f"Filters do not apply to {self.dataset_id}: {', '.join(unsupported)}"
            )
        grain = supplied.get("grain")
        allowed_grains = {item.value for item in self.grains}
        if grain is not None and str(grain) not in allowed_grains:
            raise ValueError(f"Grain does not apply to {self.dataset_id}: {grain}")
        return supplied
