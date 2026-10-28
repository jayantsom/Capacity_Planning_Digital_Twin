"""S&OP Planning APIRouter."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from capacity_twin_core.planning.runtime import PlanningNotReadyError
from demand_supply_planning.backend.models import SopFilters
from demand_supply_planning.backend.service import dashboard_payload, filters_payload, health

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
router = APIRouter(tags=["demand-supply-planning"])
SopView = Literal["executive", "demand-planner", "capacity-planner"]


def sop_filters(
    request: Request,
    site: str | None = Query(default=None, max_length=80),
    product: str | None = Query(default=None, max_length=120),
    planning_version: str | None = Query(default=None, max_length=80),
    month_from: int | None = Query(default=None, ge=200001, le=220012),
    month_to: int | None = Query(default=None, ge=200001, le=220012),
) -> SopFilters:
    allowed = {"site", "product", "planning_version", "month_from", "month_to"}
    unsupported = sorted(set(request.query_params) - allowed)
    if unsupported:
        raise HTTPException(422, f"Unsupported S&OP filters: {', '.join(unsupported)}")
    try:
        return SopFilters(
            site=site,
            product=product,
            planning_version=planning_version,
            month_from=month_from,
            month_to=month_to,
        )
    except ValidationError as error:
        raise HTTPException(422, error.errors(include_context=False, include_url=False)) from error


@router.get("/demand-supply-planning/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@router.get("/demand-supply-planning/api/health")
async def health_route() -> dict:
    return health()


@router.get("/demand-supply-planning/api/filters/{view}")
async def filter_route(view: SopView, request: Request) -> dict:
    if request.query_params:
        raise HTTPException(422, "Filter metadata does not accept query filters.")
    try:
        return filters_payload(view)
    except PlanningNotReadyError as error:
        raise HTTPException(503, f"S&OP Planning is not ready. {error}") from error


@router.get("/demand-supply-planning/api/dashboard/{view}")
async def dashboard_route(
    view: SopView,
    selected: Annotated[SopFilters, Depends(sop_filters)],
) -> dict:
    try:
        return dashboard_payload(view, selected)
    except PlanningNotReadyError as error:
        raise HTTPException(503, f"S&OP Planning is not ready. {error}") from error
