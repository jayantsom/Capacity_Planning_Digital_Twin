"""Validated model-output contracts for routing and tool selection."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DomainName = Literal["capacity", "yield", "maintenance", "forecast", "capex"]


class RouterDecision(BaseModel):
    """One schema-validated routing decision."""

    model_config = ConfigDict(extra="forbid")

    domain: DomainName
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=300)


class ToolCallContract(BaseModel):
    """One schema-validated local tool invocation."""

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=100)
    args: dict = Field(default_factory=dict)


class ToolPlan(BaseModel):
    """A bounded list of tool calls selected by the model."""

    model_config = ConfigDict(extra="forbid")

    calls: list[ToolCallContract] = Field(default_factory=list, max_length=5)
