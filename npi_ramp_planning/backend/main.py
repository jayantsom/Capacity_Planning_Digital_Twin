"""NPI Ramp Planning APIRouter."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from capacity_twin_core.planning.runtime import PlanningNotReadyError
from npi_ramp_planning.backend.models import NpiFilters
from npi_ramp_planning.backend.service import dashboard_payload, filters_payload, health

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
router = APIRouter(tags=["npi-ramp-planning"])
NpiView = Literal["program", "manufacturing", "test", "yield"]


def npi_filters(
    request: Request,
    program: str | None = Query(default=None, max_length=80),
    site: str | None = Query(default=None, max_length=80),
    product: str | None = Query(default=None, max_length=120),
    month_from: int | None = Query(default=None, ge=200001, le=220012),
    month_to: int | None = Query(default=None, ge=200001, le=220012),
) -> NpiFilters:
    allowed = {"program", "site", "product", "month_from", "month_to"}
    unsupported = sorted(set(request.query_params) - allowed)
    if unsupported:
        raise HTTPException(422, f"Unsupported NPI filters: {', '.join(unsupported)}")
    try:
        return NpiFilters(
            program=program, site=site, product=product,
            month_from=month_from, month_to=month_to,
        )
    except ValidationError as error:
        raise HTTPException(422, error.errors(include_context=False, include_url=False)) from error


@router.get("/npi-ramp-planning/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@router.get("/npi-ramp-planning/api/health")
async def health_route() -> dict:
    return health()


@router.get("/npi-ramp-planning/api/filters/{view}")
async def filter_route(view: NpiView, request: Request) -> dict:
    if request.query_params:
        raise HTTPException(422, "Filter metadata does not accept query filters.")
    try:
        return filters_payload(view)
    except PlanningNotReadyError as error:
        raise HTTPException(503, f"NPI Ramp Planning is not ready. {error}") from error


@router.get("/npi-ramp-planning/api/dashboard/{view}")
async def dashboard_route(
    view: NpiView,
    selected: Annotated[NpiFilters, Depends(npi_filters)],
) -> dict:
    try:
        return dashboard_payload(view, selected)
    except PlanningNotReadyError as error:
        raise HTTPException(503, f"NPI Ramp Planning is not ready. {error}") from error
