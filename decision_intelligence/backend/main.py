"""Decision Intelligence API and five-workflow dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import capacity_twin_core
from capacity_twin_core.jobs import GLOBAL_JOBS, JobConflict
from capacity_twin_core.runtime.database_paths import load_app_config
from decision_intelligence.backend.models import WorkflowRunRequest
from decision_intelligence.backend.service import (
    WORKFLOW_FILTERS,
    WORKFLOW_KEYS,
    WORKFLOW_METADATA,
    dashboard,
    filter_metadata,
    health_payload,
    publication_payload,
    run_workflows,
)

APP_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = APP_DIR / "frontend"
CORE_FRONTEND_DIR = Path(capacity_twin_core.__file__).resolve().parent / "frontend"
APP_CONFIG = load_app_config("decision_intelligence")
ALLOWED_ORIGINS = set(APP_CONFIG["server"]["allowed_origins"])

app = FastAPI(title="Decision Intelligence", docs_url=None, openapi_url=None)
app.mount(
    "/decision-intelligence/static",
    StaticFiles(directory=str(FRONTEND_DIR)),
    name="decision_intelligence_static",
)
app.mount("/shared", StaticFiles(directory=str(CORE_FRONTEND_DIR)), name="shared_frontend")


def _require_local_origin(request: Request) -> None:
    """Reject browser writes from an unexpected origin."""
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Origin is not allowed")


@app.get("/decision-intelligence/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the five-workflow workspace."""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/decision-intelligence/api/health")
async def health() -> dict:
    """Return ML publication readiness and staleness."""
    return health_payload()


@app.get("/decision-intelligence/api/workflows")
async def workflows() -> dict:
    """Return stable tab metadata."""
    return {"workflows": WORKFLOW_METADATA}


@app.get("/decision-intelligence/api/publication")
async def publication() -> dict:
    """Return safe provenance for the promoted model outputs."""
    try:
        return publication_payload()
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/decision-intelligence/api/filters/{workflow}")
async def workflow_filters(
    workflow: str,
    site: str | None = Query(default=None, max_length=80),
    product: str | None = Query(default=None, max_length=120),
    test_type: str | None = Query(default=None, max_length=80),
    machine: str | None = Query(default=None, max_length=120),
    planning_version: str | None = Query(default=None, max_length=80),
) -> dict:
    """Return applicable filters with full human-readable labels."""
    if workflow not in WORKFLOW_KEYS:
        raise HTTPException(status_code=404, detail="Workflow not found")
    try:
        return filter_metadata(
            workflow,
            {
                "site": site,
                "product": product,
                "test_type": test_type,
                "machine": machine,
                "planning_version": planning_version,
            },
        )
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/decision-intelligence/api/dashboard/{workflow}")
async def workflow_dashboard(
    workflow: str,
    site: str | None = Query(default=None, max_length=80),
    product: str | None = Query(default=None, max_length=120),
    test_type: str | None = Query(default=None, max_length=80),
    machine: str | None = Query(default=None, max_length=120),
    planning_version: str | None = Query(default=None, max_length=80),
    grain: Literal["WEEK", "MONTH"] | None = None,
    window: Literal["total", "band_1", "band_2"] = "total",
    month_from: int | None = Query(default=None, ge=200001, le=220012),
    month_to: int | None = Query(default=None, ge=200001, le=220012),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """Return one allowlisted dashboard dataset."""
    if workflow not in WORKFLOW_KEYS:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if month_from and month_to and month_from > month_to:
        raise HTTPException(
            status_code=422,
            detail="Month from must be on or before month to",
        )
    if window != "total" and (month_from or month_to):
        raise HTTPException(
            status_code=422,
            detail="Manual month fields are unavailable when a comparison band is active",
        )
    submitted = {
        "site": site,
        "product": product,
        "test_type": test_type,
        "machine": machine,
        "planning_version": planning_version,
        "grain": grain,
        "month_from": month_from,
        "month_to": month_to,
    }
    unsupported = sorted(
        key
        for key, value in submitted.items()
        if value not in (None, "") and key not in WORKFLOW_FILTERS[workflow]
    )
    if unsupported:
        raise HTTPException(
            status_code=422,
            detail=f"Filters do not apply to {workflow}: {', '.join(unsupported)}",
        )
    try:
        return dashboard(
            workflow,
            site=site,
            product=product,
            test_type=test_type,
            machine=machine,
            planning_version=planning_version,
            grain=grain,
            window=window,
            month_from=month_from,
            month_to=month_to,
            limit=limit,
        )
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/decision-intelligence/api/jobs", status_code=202)
async def start_job(payload: WorkflowRunRequest, request: Request) -> dict:
    """Run all workflows or one safely preserved selected set."""
    _require_local_origin(request)
    priorities = payload.priorities
    try:
        return GLOBAL_JOBS.start(
            "decision-intelligence",
            lambda report: run_workflows(priorities, report),
            metadata={"priorities": priorities or list(range(1, 6))},
        )
    except JobConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/decision-intelligence/api/jobs")
async def jobs(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """Return Decision Intelligence job history."""
    history = [
        job
        for job in GLOBAL_JOBS.history(limit=100)
        if job.get("kind") == "decision-intelligence"
    ]
    return {"jobs": history[:limit]}


@app.get("/decision-intelligence/api/jobs/{job_id}")
async def job(job_id: str) -> dict:
    """Return one workflow job."""
    try:
        result = GLOBAL_JOBS.get(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Job not found") from error
    if result.get("kind") != "decision-intelligence":
        raise HTTPException(status_code=404, detail="Job not found")
    return result
