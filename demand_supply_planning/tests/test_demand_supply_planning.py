"""S&OP API, route, filter, chart, and session contracts."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from capacity_twin_core.applications import APPLICATIONS
from demand_supply_planning.backend.main import router
from demand_supply_planning.backend.models import SopFilters

client_app = FastAPI()
client_app.include_router(router)
client = TestClient(client_app)
ROOT = Path(__file__).resolve().parents[1]


def test_role_routes_and_registry() -> None:
    item = next(app for app in APPLICATIONS if app.app_id == "demand-supply-planning")
    assert item.enabled and item.group == "planning"
    assert client.get("/demand-supply-planning/").status_code == 200
    response = client.get(
        "/demand-supply-planning/api/dashboard/executive",
        params={"unsupported": "x"},
    )
    assert response.status_code == 422
    assert client.get("/demand-supply-planning/api/dashboard/not-a-view").status_code == 422


def test_filter_validation() -> None:
    with pytest.raises(ValueError):
        SopFilters(month_from=202612, month_to=202601)


def test_action_register_is_session_only_and_versioned() -> None:
    source = (ROOT / "frontend" / "demand-supply-planning.js").read_text(encoding="utf-8")
    assert "sessionStorage" in source
    assert "capacity-twin/sop-actions/1.0.0" in source
    assert "escapeCsvCell" in source
    assert "fetch(" not in source
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "Executive" in html and "Demand Planner" in html and "Capacity Planner" in html
    assert "/shared/static/planning.css" in html
    stylesheet = (
        ROOT.parent / "src" / "capacity_twin_core" / "frontend" / "planning.css"
    ).read_text(encoding="utf-8")
    assert "grid-template-columns: repeat(auto-fit, minmax(130px, 1fr))" in stylesheet
    assert "min-height: 66px" in stylesheet
    assert "font: 700 clamp(13px, 1.2vw, 18px) var(--ct-mono)" in stylesheet
    assert ".ct-kpi-value" in stylesheet
