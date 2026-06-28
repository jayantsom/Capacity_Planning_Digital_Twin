"""
Request / Response models for the FastAPI backend.
"""

from typing import Any
from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None   # reserved for future multi-turn support


class ToolCall(BaseModel):
    tool: str
    args: dict[str, Any] = {}


class ToolResult(BaseModel):
    tool:       str
    row_count:  int | None = None
    columns:    list[str] = []
    error:      str | None = None


class PipelineStep(BaseModel):
    step:   str    # e.g. "router", "tool_selection", "duckdb", "synthesis"
    detail: str    # human-readable detail


class ChatResponse(BaseModel):
    answer:         str
    agent:          str
    tool_results:   list[ToolResult] = []
    pipeline_steps: list[PipelineStep] = []
    error:          str | None = None
