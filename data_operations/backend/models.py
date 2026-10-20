"""Validated user controls for bounded local data runs."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class GeneratorOptions(BaseModel):
    """Safe run-specific overrides accepted by the local UI."""

    profile: Literal["small", "medium", "full"] = "medium"
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)
    actual_start: date = date(2023, 1, 1)
    actual_end: date = date(2026, 10, 31)
    forecast_start: date = date(2026, 11, 1)
    forecast_end: date = date(2027, 12, 31)
    snapshot_dates: list[date] = Field(
        default_factory=lambda: [date(2025, 10, 31), date(2026, 10, 31)],
        min_length=1,
        max_length=6,
    )
    noise_profile: Literal["low", "realistic", "stress"] = "realistic"
    max_active_sites: int | None = Field(default=None, ge=1, le=30)
    max_active_products: int | None = Field(default=None, ge=1, le=48)
    max_active_test_types: int | None = Field(default=None, ge=1, le=24)
    max_systems: int | None = Field(default=None, ge=1, le=40)
    max_fixtures_handlers: int | None = Field(default=None, ge=1, le=45)

    @model_validator(mode="after")
    def validate_dates(self) -> GeneratorOptions:
        """Keep actual, snapshot, and forecast periods consistent."""
        if self.actual_start > self.actual_end:
            raise ValueError("Actual start must be on or before actual end")
        if self.forecast_start <= self.actual_end:
            raise ValueError("Forecast start must be after actual end")
        if self.forecast_start > self.forecast_end:
            raise ValueError("Forecast start must be on or before forecast end")
        if len(set(self.snapshot_dates)) != len(self.snapshot_dates):
            raise ValueError("Snapshot dates must be unique")
        if any(
            value < self.actual_start or value > self.actual_end for value in self.snapshot_dates
        ):
            raise ValueError("Snapshot dates must stay inside the actual period")
        self.snapshot_dates = sorted(self.snapshot_dates)
        return self


class PipelineRequest(BaseModel):
    """Allowed pipeline command from the local dashboard."""

    command: Literal["run"] = "run"


class JobRequest(BaseModel):
    """Request body for generator or full rebuild jobs."""

    generator: GeneratorOptions = Field(default_factory=GeneratorOptions)


class ClearDataRequest(BaseModel):
    """Typed confirmation required by destructive local data actions."""

    confirmation: str = Field(min_length=1, max_length=32)
