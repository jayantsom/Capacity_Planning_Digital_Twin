"""Local Data Operations API and tabbed web interface."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import capacity_twin_core
from capacity_twin_core.jobs import GLOBAL_JOBS, JobConflict
from capacity_twin_core.runtime.database_paths import load_app_config
from data_operations.backend.architecture import architecture_payload
from data_operations.backend.models import (
    ClearDataRequest,
    GeneratorOptions,
    JobRequest,
    PipelineRequest,
)
from data_operations.backend.service import (
    PROFILE_KEYS,
    clear_all_data,
    clear_raw_data,
    default_options,
    estimate_run,
    health_payload,
    promoted_run_payload,
    rollback_pipeline,
    run_generator,
    run_pipeline_job,
    run_rebuild,
)

APP_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = APP_DIR / "frontend"
CORE_FRONTEND_DIR = Path(capacity_twin_core.__file__).resolve().parent / "frontend"
APP_CONFIG = load_app_config("data_operations")
ALLOWED_ORIGINS = set(APP_CONFIG["server"]["allowed_origins"])
DATA_JOB_KINDS = {"generator", "pipeline", "rebuild"}

app = FastAPI(title="Data Operations", docs_url=None, openapi_url=None)
router = APIRouter()
app.mount(
    "/data-operations/static",
    StaticFiles(directory=str(FRONTEND_DIR)),
    name="data_operations_static",
)
app.mount(
    "/shared/static",
    StaticFiles(directory=str(CORE_FRONTEND_DIR)),
    name="shared_frontend",
)


def _require_local_origin(request: Request) -> None:
    """Reject browser writes from an unexpected origin."""
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Origin is not allowed")


def _start_job(kind: str, runner, metadata: dict | None = None) -> dict:
    """Translate the global single-flight conflict into an API response."""
    try:
        return GLOBAL_JOBS.start(kind, runner, metadata=metadata)
    except JobConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def _require_safe_estimate(options: GeneratorOptions) -> None:
    """Keep oversized generator requests off the local job queue."""
    if not estimate_run(options)["within_local_limits"]:
        raise HTTPException(
            status_code=422,
            detail="The requested run exceeds the configured local safety limits",
        )


def _require_no_active_job() -> None:
    """Block destructive actions while local compute is active."""
    if GLOBAL_JOBS.active():
        raise HTTPException(status_code=409, detail="A compute job is running")


@router.get("/data-operations/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the Data Operations workspace."""
    return FileResponse(FRONTEND_DIR / "index.html")


@router.get("/data-operations/api/health")
async def health() -> dict:
    """Report local Raw and medallion readiness."""
    return await asyncio.to_thread(health_payload)


@router.get("/data-operations/api/config")
async def configuration() -> dict:
    """Return safe generator defaults and profile names."""
    options = default_options()
    return {
        "defaults": options.model_dump(mode="json"),
        "profiles": list(PROFILE_KEYS),
        "noise_profiles": ["low", "realistic", "stress"],
        "estimate": estimate_run(options),
    }


@router.get("/data-operations/api/publication")
async def publication() -> dict:
    """Return safe details for the active medallion publication."""
    try:
        return await asyncio.to_thread(promoted_run_payload)
    except (FileNotFoundError, ValueError, KeyError, OSError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/data-operations/api/architecture")
async def architecture() -> dict:
    """Return tracked lineage, formula, ownership, and catalog metadata."""
    return await asyncio.to_thread(architecture_payload)


@router.post("/data-operations/api/estimate")
async def estimate(options: GeneratorOptions, request: Request) -> dict:
    """Validate controls and estimate local resource use."""
    _require_local_origin(request)
    return estimate_run(options)


@router.post("/data-operations/api/jobs/generate", status_code=202)
async def generate(payload: JobRequest, request: Request) -> dict:
    """Start one bounded Raw-data build."""
    _require_local_origin(request)
    options = payload.generator
    _require_safe_estimate(options)
    return _start_job(
        "generator",
        lambda report: run_generator(options, report),
        options.model_dump(mode="json"),
    )


@router.post("/data-operations/api/jobs/pipeline", status_code=202)
async def pipeline(payload: PipelineRequest, request: Request) -> dict:
    """Start one complete Bronze-to-Serving build."""
    _require_local_origin(request)
    return _start_job("pipeline", run_pipeline_job, payload.model_dump())


@router.post("/data-operations/api/jobs/rebuild", status_code=202)
async def rebuild(payload: JobRequest, request: Request) -> dict:
    """Start Generator followed by the complete pipeline."""
    _require_local_origin(request)
    options = payload.generator
    _require_safe_estimate(options)
    return _start_job(
        "rebuild",
        lambda report: run_rebuild(options, report),
        options.model_dump(mode="json"),
    )


@router.get("/data-operations/api/jobs")
async def jobs(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """Return bounded local job history."""
    history = [job for job in GLOBAL_JOBS.history(limit=100) if job.get("kind") in DATA_JOB_KINDS]
    return {"jobs": history[:limit]}


@router.get("/data-operations/api/jobs/{job_id}")
async def job(job_id: str) -> dict:
    """Return progress for one known local job."""
    try:
        result = GLOBAL_JOBS.get(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Job not found") from error
    if result.get("kind") not in DATA_JOB_KINDS:
        raise HTTPException(status_code=404, detail="Job not found")
    return result


@router.post("/data-operations/api/rollback")
async def rollback(request: Request) -> dict:
    """Activate the previous validated medallion run."""
    _require_local_origin(request)
    _require_no_active_job()
    run_id = await asyncio.to_thread(rollback_pipeline)
    return {"active_run_id": run_id, "status": "ROLLED_BACK"}


@router.post("/data-operations/api/data/clear-raw")
async def clear_raw(payload: ClearDataRequest, request: Request) -> dict:
    """Clear Raw data after an exact typed confirmation."""
    _require_local_origin(request)
    _require_no_active_job()
    if payload.confirmation != "CLEAR RAW":
        raise HTTPException(status_code=422, detail="Type CLEAR RAW to confirm")
    return await asyncio.to_thread(clear_raw_data)


@router.post("/data-operations/api/data/clear-all")
async def clear_all(payload: ClearDataRequest, request: Request) -> dict:
    """Clear generated and derived data after an exact confirmation."""
    _require_local_origin(request)
    _require_no_active_job()
    if payload.confirmation != "CLEAR ALL":
        raise HTTPException(status_code=422, detail="Type CLEAR ALL to confirm")
    return await asyncio.to_thread(clear_all_data)


app.include_router(router)
