"""Single local web entry point for all Capacity Twin applications."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import capacity_twin_core
from capacity_assistant.backend.main import app as capacity_assistant_app
from capacity_twin_core.runtime.database_paths import load_app_config
from data_explorer.backend.main import app as explorer_app
from data_operations.backend.main import app as data_operations_app
from decision_intelligence.backend.main import app as decision_intelligence_app

APP_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = APP_DIR / "frontend"
CORE_FRONTEND_DIR = Path(capacity_twin_core.__file__).resolve().parent / "frontend"
APP_CONFIG = load_app_config("capacity_home")

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
    "/shared",
    StaticFiles(directory=str(CORE_FRONTEND_DIR)),
    name="shared_frontend",
)


@app.get("/", include_in_schema=False)
async def home_index() -> FileResponse:
    """Serve the compact application launcher."""
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/capacity-assistant", include_in_schema=False)
async def capacity_assistant_redirect() -> RedirectResponse:
    """Use one canonical URL for Capacity Assistant assets and navigation."""
    return RedirectResponse("/capacity-assistant/", status_code=307)


@app.get("/capacity-assistant/", include_in_schema=False)
async def capacity_assistant_index() -> FileResponse:
    """Serve Capacity Assistant from the shared local web process."""
    return FileResponse(APP_DIR.parent / "capacity_assistant" / "frontend" / "index.html")


def _adopt_routes(source: FastAPI, prefixes: tuple[str, ...]) -> None:
    """Attach selected app-owned routes without starting another server."""
    for route in source.router.routes:
        path = getattr(route, "path", "")
        if path.startswith(prefixes):
            app.router.routes.append(route)


# Keep each app's routes in its own module while exposing one local server.
_adopt_routes(capacity_assistant_app, ("/api", "/static"))
_adopt_routes(explorer_app, ("/explorer",))
_adopt_routes(data_operations_app, ("/data-operations",))
_adopt_routes(decision_intelligence_app, ("/decision-intelligence",))


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
