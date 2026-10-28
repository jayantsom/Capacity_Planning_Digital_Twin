"""Typed Operations Flow filters."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator


class FlowFilters(BaseModel):
    site: str | None = Field(default=None, max_length=80)
    product: str | None = Field(default=None, max_length=120)
    operation: str | None = Field(default=None, max_length=120)
    resource: str | None = Field(default=None, max_length=120)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def valid_range(self) -> FlowFilters:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Date from must be on or before date to")
        return self
