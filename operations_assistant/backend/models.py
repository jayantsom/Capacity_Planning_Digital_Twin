"""
Request / Response models for the FastAPI backend.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class PageContext(BaseModel):
    app_id: Literal[
        "home",
        "data-explorer",
        "capacity-analysis",
        "decision-intelligence",
        "scenario-planning",
        "demand-supply-planning",
        "npi-ramp-planning",
        "operations-flow",
        "data-operations",
        "documentation",
    ] = "home"
    path: str = Field(default="/", max_length=200)
    view: str | None = Field(default=None, max_length=100)
    selected_table: str | None = Field(default=None, max_length=150)
    filters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4_000)
    session_id: str | None = None   # reserved for future multi-turn support
    context: PageContext = Field(default_factory=PageContext)


class ToolCall(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool:       str
    row_count:  int | None = None
    columns:    list[str] = Field(default_factory=list)
    error:      str | None = None


class PipelineStep(BaseModel):
    step:   str    # e.g. "router", "tool_selection", "duckdb", "synthesis"
    detail: str    # human-readable detail


class ChatResponse(BaseModel):
    answer:         str
    agent:          str
    tool_results:   list[ToolResult] = Field(default_factory=list)
    pipeline_steps: list[PipelineStep] = Field(default_factory=list)
    error:          str | None = None
