"""Scenario and What-If Planning APIRouter."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from capacity_twin_core.planning.runtime import PlanningNotReadyError
from scenario_planning.backend.models import ScenarioFilters
from scenario_planning.backend.service import baseline_payload, filters_payload, health

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
router = APIRouter(tags=["scenario-planning"])


def scenario_filters(
    request: Request,
    site: str | None = Query(default=None, max_length=80),
    product: str | None = Query(default=None, max_length=120),
    planning_version: str | None = Query(default=None, max_length=80),
    month_from: int | None = Query(default=None, ge=200001, le=220012),
    month_to: int | None = Query(default=None, ge=200001, le=220012),
) -> ScenarioFilters:
    allowed = {"site", "product", "planning_version", "month_from", "month_to"}
    unsupported = sorted(set(request.query_params) - allowed)
    if unsupported:
        raise HTTPException(422, f"Unsupported Scenario Planning filters: {', '.join(unsupported)}")
    try:
        return ScenarioFilters(
            site=site,
            product=product,
            planning_version=planning_version,
            month_from=month_from,
            month_to=month_to,
        )
    except ValidationError as error:
        raise HTTPException(422, error.errors(include_context=False, include_url=False)) from error


@router.get("/scenario-planning/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@router.get("/scenario-planning/api/health")
async def health_route() -> dict:
    return health()


@router.get("/scenario-planning/api/filters")
async def filter_route(request: Request) -> dict:
    if request.query_params:
        raise HTTPException(422, "Filter metadata does not accept query filters.")
    try:
        return filters_payload()
    except PlanningNotReadyError as error:
        raise HTTPException(503, f"Scenario Planning is not ready. {error}") from error


@router.get("/scenario-planning/api/baseline")
async def baseline_route(
    selected: Annotated[ScenarioFilters, Depends(scenario_filters)],
) -> dict:
    try:
        return baseline_payload(selected)
    except PlanningNotReadyError as error:
        raise HTTPException(503, f"Scenario Planning is not ready. {error}") from error
