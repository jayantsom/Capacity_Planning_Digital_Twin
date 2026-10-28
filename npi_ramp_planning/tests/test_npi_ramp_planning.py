"""NPI API, route, filter, chart, and truthfulness contracts."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from capacity_twin_core.applications import APPLICATIONS
from npi_ramp_planning.backend.main import router
from npi_ramp_planning.backend.models import NpiFilters

client_app = FastAPI()
client_app.include_router(router)
client = TestClient(client_app)
ROOT = Path(__file__).resolve().parents[1]


def test_role_routes_registry_and_filter_rejection() -> None:
    item = next(app for app in APPLICATIONS if app.app_id == "npi-ramp-planning")
    assert item.enabled and item.group == "planning"
    assert client.get("/npi-ramp-planning/").status_code == 200
    assert client.get("/npi-ramp-planning/api/dashboard/yield?machine=x").status_code == 422
    assert client.get("/npi-ramp-planning/api/dashboard/unknown").status_code == 422


def test_filter_validation() -> None:
    with pytest.raises(ValueError):
        NpiFilters(month_from=202600)


def test_learning_curve_and_stage_gate_guards_are_visible() -> None:
    service = (ROOT / "backend" / "service.py").read_text(encoding="utf-8")
    assert 'len(learning_rows) >= 2' in service
    assert '"stage_gate_timeline"' in service
    assert "srv_npi_stage_gate" in service
    source = (ROOT / "frontend" / "npi-ramp-planning.js").read_text(encoding="utf-8")
    assert "learning_curve.available" in source
    assert "stage_gate_timeline.reason" in source
    assert "timeline-chart" in source
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    for role in ("Program", "Manufacturing", "Test", "Yield"):
        assert role in html
