"""Capacity Analysis APIRouter and standalone development app."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from capacity_analysis.backend.models import CapacityFilters
from capacity_analysis.backend.service import (
    CapacityNotReadyError,
    bottleneck_payload,
    filter_payload,
    health_payload,
    tactical_payload,
)

APP_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = APP_DIR / "frontend"

router = APIRouter(tags=["capacity-analysis"])
app = FastAPI(title="Capacity Analysis", docs_url=None, openapi_url=None)
app.mount(
    "/capacity-analysis/static",
    StaticFiles(directory=str(FRONTEND_DIR)),
    name="capacity_analysis_static",
)


def capacity_filters(
    request: Request,
    site: str | None = Query(default=None, max_length=80),
    product: str | None = Query(default=None, max_length=120),
    test_type: str | None = Query(default=None, max_length=80),
    capacity_mode: Literal["NORMAL", "MAXIMUM"] = "NORMAL",
    retest: Literal["NONE", "TYPE1", "TYPE2"] = "NONE",
    planning_version: str | None = Query(default=None, max_length=80),
    month_from: int | None = Query(default=None, ge=200001, le=220012),
    month_to: int | None = Query(default=None, ge=200001, le=220012),
) -> CapacityFilters:
    """Validate the complete server-declared filter set."""
    allowed = {
        "site",
        "product",
        "test_type",
        "capacity_mode",
        "retest",
        "planning_version",
        "month_from",
        "month_to",
    }
    unsupported = sorted(set(request.query_params) - allowed)
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported Capacity Analysis filters: {', '.join(unsupported)}",
        )
    try:
        return CapacityFilters(
            site=site,
            product=product,
            test_type=test_type,
            capacity_mode=capacity_mode,
            retest=retest,
            planning_version=planning_version,
            month_from=month_from,
            month_to=month_to,
        )
    except ValidationError as error:
        raise HTTPException(
            status_code=422,
            detail=error.errors(include_context=False, include_url=False),
        ) from error


@router.get("/capacity-analysis/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve Tactical Capacity and Bottleneck Analysis."""
    return FileResponse(FRONTEND_DIR / "index.html")


@router.get("/capacity-analysis/api/health")
async def health() -> dict:
    """Return a clear ready or not-ready release state."""
    return health_payload()


@router.get("/capacity-analysis/api/filters/{tab}")
async def filters(
    tab: Literal["tactical", "bottlenecks"],
    request: Request,
) -> dict:
    """Return applicable filters with full labels and codes."""
    if request.query_params:
        raise HTTPException(
            status_code=422,
            detail="Filter metadata does not accept query filters.",
        )
    try:
        return filter_payload(tab)
    except CapacityNotReadyError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/capacity-analysis/api/tactical")
async def tactical(
    selected: Annotated[CapacityFilters, Depends(capacity_filters)],
) -> dict:
    """Return the bounded Tactical Capacity dashboard contract."""
    try:
        return tactical_payload(selected)
    except CapacityNotReadyError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/capacity-analysis/api/bottlenecks")
async def bottlenecks(
    selected: Annotated[CapacityFilters, Depends(capacity_filters)],
) -> dict:
    """Return the bounded Bottleneck Analysis dashboard contract."""
    try:
        return bottleneck_payload(selected)
    except CapacityNotReadyError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


app.include_router(router)
