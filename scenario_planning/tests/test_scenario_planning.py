"""Scenario API, route, filter, chart, and session contracts."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from capacity_twin_core.applications import APPLICATIONS
from scenario_planning.backend.main import router
from scenario_planning.backend.models import ScenarioFilters

client_app = FastAPI()
client_app.include_router(router)
client = TestClient(client_app)
ROOT = Path(__file__).resolve().parents[1]


def test_route_registry_and_unsupported_filter() -> None:
    item = next(app for app in APPLICATIONS if app.app_id == "scenario-planning")
    assert item.enabled and item.group == "planning"
    assert client.get("/scenario-planning/").status_code == 200
    assert client.get("/scenario-planning/api/baseline?machine=EQ1").status_code == 422


def test_not_ready_is_clear_and_runtime_is_not_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CAPACITY_TWIN_HOME", str(tmp_path))
    payload = client.get("/scenario-planning/api/health").json()
    assert payload["status"] == "not-ready"
    assert list(tmp_path.iterdir()) == []


def test_filter_validation_and_session_frontend_contract() -> None:
    with pytest.raises(ValueError):
        ScenarioFilters(month_from=202613)
    source = (ROOT / "frontend" / "scenario-planning.js").read_text(encoding="utf-8")
    assert "sessionStorage" in source
    assert "capacity-twin/scenario/1.0.0" in source
    assert "escapeCsvCell" in source
    assert "renderGovernedChart" not in source
    assert "chartSpec" in source
