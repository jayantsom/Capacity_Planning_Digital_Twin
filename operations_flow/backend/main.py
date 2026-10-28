"""Operations Flow APIRouter."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from capacity_twin_core.planning.runtime import PlanningNotReadyError
from operations_flow.backend.models import FlowFilters
from operations_flow.backend.service import dashboard_payload, filters_payload, health

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
router = APIRouter(tags=["operations-flow"])
FlowView = Literal["production-control", "industrial-engineering", "test-operations"]


def flow_filters(
    request: Request,
    site: str | None = Query(default=None, max_length=80),
    product: str | None = Query(default=None, max_length=120),
    operation: str | None = Query(default=None, max_length=120),
    resource: str | None = Query(default=None, max_length=120),
    date_from: date | None = None,
    date_to: date | None = None,
) -> FlowFilters:
    allowed = {"site", "product", "operation", "resource", "date_from", "date_to"}
    unsupported = sorted(set(request.query_params) - allowed)
    if unsupported:
        raise HTTPException(422, f"Unsupported Operations Flow filters: {', '.join(unsupported)}")
    try:
        return FlowFilters(
            site=site, product=product, operation=operation, resource=resource,
            date_from=date_from, date_to=date_to,
        )
    except ValidationError as error:
        raise HTTPException(422, error.errors(include_context=False, include_url=False)) from error


@router.get("/operations-flow/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@router.get("/operations-flow/api/health")
async def health_route() -> dict:
    return health()


@router.get("/operations-flow/api/filters/{view}")
async def filter_route(view: FlowView, request: Request) -> dict:
    if request.query_params:
        raise HTTPException(422, "Filter metadata does not accept query filters.")
    try:
        return filters_payload(view)
    except PlanningNotReadyError as error:
        raise HTTPException(503, f"Operations Flow is not ready. {error}") from error


@router.get("/operations-flow/api/dashboard/{view}")
async def dashboard_route(
    view: FlowView,
    selected: Annotated[FlowFilters, Depends(flow_filters)],
) -> dict:
    try:
        return dashboard_payload(view, selected)
    except PlanningNotReadyError as error:
        raise HTTPException(503, f"Operations Flow is not ready. {error}") from error
