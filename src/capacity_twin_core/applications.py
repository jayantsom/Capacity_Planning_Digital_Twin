"""Typed registry for local Capacity Twin applications and navigation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import import_module
from pathlib import Path
from typing import Literal

from fastapi import APIRouter

from capacity_twin_core.runtime.database_paths import PROJECT_ROOT

ApplicationGroup = Literal["primary", "operations", "reference"]


@dataclass(frozen=True, slots=True)
class Application:
    """Public application metadata used by composition and the shared shell."""

    app_id: str
    title: str
    route: str
    monogram: str
    description: str
    group: ApplicationGroup
    health_route: str | None = None
    router_module: str | None = None
    static_directory: str | None = None
    enabled: bool = True
    show_on_home: bool = True

    def public_dict(self) -> dict[str, object]:
        """Return browser-safe registry metadata."""
        payload = asdict(self)
        payload.pop("router_module")
        payload.pop("static_directory")
        return payload

    def load_router(self) -> APIRouter:
        """Load an enabled app's public router without importing private services."""
        if not self.router_module:
            raise ValueError(f"{self.app_id} does not declare a router")
        router = getattr(import_module(self.router_module), "router", None)
        if not isinstance(router, APIRouter):
            raise TypeError(f"{self.router_module}.router must be an APIRouter")
        return router

    def static_path(self) -> Path | None:
        """Resolve an app-owned source-checkout static directory."""
        return PROJECT_ROOT / self.static_directory if self.static_directory else None


APPLICATIONS: tuple[Application, ...] = (
    Application(
        "home",
        "Home",
        "/",
        "CP",
        "Local planning workspace",
        "primary",
        show_on_home=False,
    ),
    Application(
        "data-explorer",
        "Data Explorer",
        "/explorer/",
        "DX",
        "Governed source and publication data",
        "primary",
        "/explorer/api/sources",
        "data_explorer.backend.main",
        "data_explorer/frontend",
    ),
    Application(
        "capacity-analysis",
        "Capacity Analysis",
        "/capacity-analysis/",
        "CA",
        "Tactical capacity and bottlenecks",
        "primary",
        "/capacity-analysis/api/health",
        "capacity_analysis.backend.main",
        "capacity_analysis/frontend",
    ),
    Application(
        "decision-intelligence",
        "Decision Intelligence",
        "/decision-intelligence/",
        "DI",
        "Five governed ML workflows",
        "primary",
        "/decision-intelligence/api/health",
        "decision_intelligence.backend.main",
        "decision_intelligence/frontend",
    ),
    Application(
        "data-operations",
        "Data Operations",
        "/data-operations/",
        "DO",
        "Raw generation and publication pipelines",
        "operations",
        "/data-operations/api/health",
        "data_operations.backend.main",
        "data_operations/frontend",
    ),
    Application(
        "documentation",
        "Documentation",
        "/documentation/",
        "DC",
        "Governed product documentation",
        "reference",
        "/documentation/api/health",
        "documentation.backend.main",
        "documentation/frontend",
    ),
)


def validate_registry(applications: tuple[Application, ...] = APPLICATIONS) -> None:
    """Fail fast on ambiguous or reserved application declarations."""
    ids = [item.app_id for item in applications]
    routes = [item.route for item in applications]
    if len(ids) != len(set(ids)):
        raise ValueError("Application IDs must be unique")
    if len(routes) != len(set(routes)):
        raise ValueError("Application routes must be unique")
    for item in applications:
        if item.route.startswith(("/shared/static", "/shared/api")):
            raise ValueError(f"{item.app_id} uses a reserved shared route")
        if item.static_directory and not item.enabled:
            raise ValueError(f"Disabled application {item.app_id} declares static assets")


def enabled_applications() -> tuple[Application, ...]:
    """Return currently routed applications in registry order."""
    return tuple(item for item in APPLICATIONS if item.enabled)


validate_registry()
