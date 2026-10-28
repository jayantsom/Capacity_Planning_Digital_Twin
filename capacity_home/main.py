"""Registry-composed local web entry point for Capacity Twin applications."""

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import capacity_twin_core
from capacity_twin_core.applications import APPLICATIONS, enabled_applications
from capacity_twin_core.runtime.database_paths import load_app_config
from operations_assistant.backend.main import router as yukti_router

APP_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = APP_DIR / "frontend"
CORE_FRONTEND_DIR = Path(capacity_twin_core.__file__).resolve().parent / "frontend"
APP_CONFIG = load_app_config("capacity_home")
home_router = APIRouter()
shared_router = APIRouter(prefix="/shared/api", tags=["shared"])
COMPOSED_ROUTE_PATHS: tuple[str, ...] = ()
COMPOSED_ROUTE_KEYS: tuple[tuple[str, str], ...] = ()

app = FastAPI(
    title="Capacity Planning Digital Twin",
    version="0.2.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=APP_CONFIG["server"]["allowed_origins"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.mount("/home/static", StaticFiles(directory=str(FRONTEND_DIR)), name="home_static")
app.mount(
    "/shared/static",
    StaticFiles(directory=str(CORE_FRONTEND_DIR)),
    name="shared_static",
)


@home_router.get("/", include_in_schema=False)
async def home_index() -> FileResponse:
    """Serve the compact application launcher."""
    return FileResponse(FRONTEND_DIR / "index.html")


@shared_router.get("/applications")
async def application_catalog() -> dict[str, object]:
    """Expose the same safe registry metadata used to compose this process."""
    return {"applications": [item.public_dict() for item in APPLICATIONS]}


@shared_router.get("/health")
async def shared_health() -> dict[str, object]:
    """Report configured application routes without coupling their readiness."""
    route_paths = set(COMPOSED_ROUTE_PATHS)
    applications = [
        {
            "app_id": item.app_id,
            "route": item.route,
            "configured": item.enabled,
            "routed": item.route in route_paths,
            "health_route": item.health_route,
        }
        for item in APPLICATIONS
    ]
    return {
        "status": "ready"
        if all(item["routed"] for item in applications if item["configured"])
        else "degraded",
        "applications": applications,
    }


app.include_router(home_router)
app.include_router(shared_router)
app.include_router(yukti_router)

composed_paths = [
    *(route.path for route in home_router.routes),
    *(route.path for route in shared_router.routes),
    *(route.path for route in yukti_router.routes),
    "/home/static",
    "/shared/static",
]
composed_keys = [
    (route.path, method)
    for route in (*home_router.routes, *shared_router.routes, *yukti_router.routes)
    for method in (route.methods or {"MOUNT"})
]
composed_keys.extend((path, "MOUNT") for path in ("/home/static", "/shared/static"))
for application in enabled_applications():
    if application.router_module:
        application_router = application.load_router()
        composed_paths.extend(route.path for route in application_router.routes)
        composed_keys.extend(
            (route.path, method)
            for route in application_router.routes
            for method in (route.methods or {"MOUNT"})
        )
        app.include_router(application_router)
    static_path = application.static_path()
    if static_path:
        static_route = f"{application.route.rstrip('/')}/static"
        composed_paths.append(static_route)
        composed_keys.append((static_route, "MOUNT"))
        app.mount(
            static_route,
            StaticFiles(directory=str(static_path)),
            name=f"{application.app_id}-static",
        )

if len(composed_keys) != len(set(composed_keys)):
    duplicates = sorted(key for key in set(composed_keys) if composed_keys.count(key) > 1)
    raise RuntimeError(f"Duplicate composed application route methods: {duplicates}")
COMPOSED_ROUTE_PATHS = tuple(dict.fromkeys(composed_paths))
COMPOSED_ROUTE_KEYS = tuple(composed_keys)


def main() -> None:
    """Run the combined local application."""
    import uvicorn

    uvicorn.run(
        "capacity_home.main:app",
        host=APP_CONFIG["server"]["host"],
        port=APP_CONFIG["server"]["port"],
        reload=False,
    )


if __name__ == "__main__":
    main()
