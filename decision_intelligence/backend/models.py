"""Validated requests for Decision Intelligence jobs."""

from pydantic import BaseModel, Field


class WorkflowRunRequest(BaseModel):
    """Run every workflow or a safe selected subset."""

    priorities: list[int] | None = Field(default=None, min_length=1, max_length=5)
