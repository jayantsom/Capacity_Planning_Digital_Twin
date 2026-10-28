"""Typed public contracts for Capacity Analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

CapacityMode = Literal["NORMAL", "MAXIMUM"]
RetestModel = Literal["NONE", "TYPE1", "TYPE2"]
AnalysisTab = Literal["tactical", "bottlenecks"]


class CapacityFilters(BaseModel):
    """Allowlisted filters shared by the two capacity views."""

    site: str | None = Field(default=None, max_length=80)
    product: str | None = Field(default=None, max_length=120)
    test_type: str | None = Field(default=None, max_length=80)
    capacity_mode: CapacityMode = "NORMAL"
    retest: RetestModel = "NONE"
    planning_version: str | None = Field(default=None, max_length=80)
    month_from: int | None = Field(default=None, ge=200001, le=220012)
    month_to: int | None = Field(default=None, ge=200001, le=220012)

    @model_validator(mode="after")
    def validate_month_range(self) -> CapacityFilters:
        if (
            self.month_from is not None
            and self.month_to is not None
            and self.month_from > self.month_to
        ):
            raise ValueError("Month from must be on or before month to")
        for value, name in (
            (self.month_from, "month_from"),
            (self.month_to, "month_to"),
        ):
            if value is not None and not 1 <= value % 100 <= 12:
                raise ValueError(f"{name} must contain a valid calendar month")
        return self


class FilterOption(BaseModel):
    """One code with a full human-readable label."""

    value: str
    label: str
    code: str


class WaterfallComponent(BaseModel):
    """One signed capacity bridge component."""

    label: str
    value: float
    kind: Literal["start", "loss", "end"]


class CapacityWaterfall(BaseModel):
    """Exactly reconciled Maximum-to-Normal capacity bridge."""

    maximum_capacity: float
    components: list[WaterfallComponent]
    normal_capacity: float
    reconciliation_delta: float


def reconcile_capacity_waterfall(
    maximum_capacity: float,
    normal_capacity: float,
) -> CapacityWaterfall:
    """Bridge Maximum Capacity to Normal Capacity without hidden residuals."""
    maximum = round(float(maximum_capacity or 0), 6)
    normal = round(float(normal_capacity or 0), 6)
    schedule_loss = round(normal - maximum, 6)
    reconciled = round(maximum + schedule_loss, 6)
    delta = round(normal - reconciled, 6)
    return CapacityWaterfall(
        maximum_capacity=maximum,
        components=[
            WaterfallComponent(
                label="Maximum Capacity",
                value=maximum,
                kind="start",
            ),
            WaterfallComponent(
                label="Planned operating schedule loss",
                value=schedule_loss,
                kind="loss",
            ),
            WaterfallComponent(
                label="Normal Capacity",
                value=normal,
                kind="end",
            ),
        ],
        normal_capacity=normal,
        reconciliation_delta=delta,
    )
