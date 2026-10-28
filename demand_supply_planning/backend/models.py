"""Typed S&OP request contracts."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SopFilters(BaseModel):
    site: str | None = Field(default=None, max_length=80)
    product: str | None = Field(default=None, max_length=120)
    planning_version: str | None = Field(default=None, max_length=80)
    month_from: int | None = Field(default=None, ge=200001, le=220012)
    month_to: int | None = Field(default=None, ge=200001, le=220012)

    @model_validator(mode="after")
    def valid_range(self) -> SopFilters:
        for value in (self.month_from, self.month_to):
            if value is not None and not 1 <= value % 100 <= 12:
                raise ValueError("Month filters must contain a valid calendar month")
        if self.month_from and self.month_to and self.month_from > self.month_to:
            raise ValueError("Month from must be on or before month to")
        return self
