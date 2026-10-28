"""Operations API, route, filter, chart, and Sankey-gate contracts."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from capacity_twin_core.applications import APPLICATIONS
from operations_flow.backend.main import router
from operations_flow.backend.models import FlowFilters
from operations_flow.backend.service import DATASET_FILTERS

client_app = FastAPI()
client_app.include_router(router)
client = TestClient(client_app)
ROOT = Path(__file__).resolve().parents[1]


def test_role_routes_registry_and_filter_rejection() -> None:
    item = next(app for app in APPLICATIONS if app.app_id == "operations-flow")
    assert item.enabled and item.group == "planning"
    assert client.get("/operations-flow/").status_code == 200
    assert client.get("/operations-flow/api/dashboard/production-control?month=202601").status_code == 422
    assert client.get("/operations-flow/api/dashboard/unknown").status_code == 422


def test_filter_validation_and_dataset_applicability() -> None:
    with pytest.raises(ValueError):
        FlowFilters(date_from="2026-02-01", date_to="2026-01-01")
    assert "product" not in DATASET_FILTERS["queue"]
    assert DATASET_FILTERS["schedule_attainment"] == [
        "site", "product", "date_from", "date_to",
    ]


def test_chart_contracts_and_sankey_use_published_route_flow() -> None:
    source = (ROOT / "frontend" / "operations-flow.js").read_text(encoding="utf-8")
    for chart in ("queue-heatmap", "cycle-chart", "control-chart", "bottleneck-chart"):
        assert chart in source
    service = (ROOT / "backend" / "service.py").read_text(encoding="utf-8")
    assert '"sankey"' in service
    assert 'bool(data["route_flow"])' in service
    assert "srv_operations_route_flow" in service
    assert "sankey-chart" in source
    assert "route_step_sequence" in source
    assert "`FROM · ${row.from_operation}`" in source
    serving = (
        ROOT.parent
        / "data_operations"
        / "pipeline"
        / "pipeline"
        / "gold"
        / "serving_views.py"
    ).read_text(encoding="utf-8")
    assert "route_id," in serving
    assert "route_step_sequence," in serving
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    for role in ("Production Control", "Industrial Engineering", "Test Operations"):
        assert role in html
