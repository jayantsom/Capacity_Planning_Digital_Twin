"""Integrated Phase 6 planning APIs against one temporary self-contained release."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from capacity_home.main import app
from data_operations.pipeline.pipeline.gold.planning_foundation import (
    build_planning_foundation,
)
from data_operations.pipeline.pipeline.gold.serving_views import SERVING_VIEWS
from data_operations.pipeline.tests.unit.test_phase6_planning_foundation import (
    _expose_source_tables,
    _source_config,
)

client = TestClient(app)
PHASE6_TABLES = {
    name for name in SERVING_VIEWS
    if name.startswith(("srv_sop_", "srv_npi_", "srv_operations_", "srv_scenario_"))
}


@pytest.fixture()
def planning_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Build a tiny release outside active runtime and pin every API to it."""
    monkeypatch.setenv("CAPACITY_TWIN_HOME", str(tmp_path))
    config = _source_config(tmp_path)
    database = tmp_path / "candidate" / "serving.duckdb"
    database.parent.mkdir()
    with duckdb.connect(str(database)) as connection:
        _expose_source_tables(connection, config)
        build_planning_foundation(connection)
        for table in PHASE6_TABLES:
            connection.execute(f'CREATE TABLE "{table}" AS {SERVING_VIEWS[table]}')
        connection.execute(
            """
            CREATE TABLE srv_vw_capacity_summary AS
            SELECT site_code, site_code AS site_name, product_number,
                   product_number AS product_description, month_key,
                   planning_version_id, plan_as_of_date,
                   'NORMAL' AS capacity_mode, 'NONE' AS retest_type,
                   customer_order_quantity_ea AS demand_qty,
                   constrained_production_ea AS capacity_qty,
                   constrained_production_ea - customer_order_quantity_ea AS gap_qty
            FROM gold_sop_balance
            """
        )
        connection.execute(
            """
            CREATE TABLE srv_resource_constraints AS
            SELECT month_key, planning_version_id, site_code,
                   site_code AS site_name, product_number,
                   product_number AS product_description,
                   'TEST' AS test_type, 'Test operation' AS test_category_name,
                   'NORMAL' AS capacity_mode,
                   'NONE' AS retest_type, 'RESOURCE-1' AS resource_constraint_id,
                   'Test resource' AS equipment_name,
                   'DEDICATED' AS resource_behavior, 'TESTER' AS equipment_type,
                   10.0 AS required_resource_hours, 8.0 AS available_resource_hours,
                   -2.0 AS gap_resource_hours, 'HIGH' AS bottleneck_severity
            FROM gold_sop_balance
            """
        )
    (tmp_path / "release_current.json").write_text(
        json.dumps(
            {
                "release_id": "phase6-test",
                "promoted_at": "2026-10-27T00:00:00Z",
                "publications": {
                    "serving": {"run_id": "phase6-pipeline", "path": str(database)}
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("filters_path", "dashboard_path"),
    [
        ("/scenario-planning/api/filters", "/scenario-planning/api/baseline"),
        (
            "/demand-supply-planning/api/filters/executive",
            "/demand-supply-planning/api/dashboard/executive",
        ),
        (
            "/npi-ramp-planning/api/filters/program",
            "/npi-ramp-planning/api/dashboard/program",
        ),
        (
            "/operations-flow/api/filters/production-control",
            "/operations-flow/api/dashboard/production-control",
        ),
    ],
)
def test_planning_filter_and_dashboard_contracts(
    planning_release: None,
    filters_path: str,
    dashboard_path: str,
) -> None:
    filters = client.get(filters_path)
    assert filters.status_code == 200, filters.text
    assert filters.json()["status"] == "ready"
    dashboard = client.get(dashboard_path)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["status"] in {"ready", "empty"}
    assert dashboard.json()["release"]["release_id"] == "phase6-test"
    assert dashboard.json()["limits"]["chart_points"] <= 800
