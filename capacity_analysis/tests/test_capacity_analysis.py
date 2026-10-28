"""API, filter, formula, route, and chart-contract checks."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from capacity_analysis.backend.models import reconcile_capacity_waterfall
from capacity_home.main import app
from capacity_twin_core.applications import APPLICATIONS

client = TestClient(app)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def promoted_serving(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Publish a tiny self-contained Serving release without touching runtime."""
    monkeypatch.setenv("CAPACITY_TWIN_HOME", str(tmp_path))
    database = tmp_path / "artifacts" / "release-1" / "serving.duckdb"
    database.parent.mkdir(parents=True)
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            CREATE TABLE srv_vw_capacity_summary AS
            SELECT * FROM (VALUES
              ('S1','Austin Factory','P1','Router Board','TT1',202601,'PV1',
               DATE '2025-12-01','NORMAL','NONE','Tester',100.0,90.0,-10.0,
               -0.10,1.111,1.0,0.0),
              ('S1','Austin Factory','P1','Router Board','TT1',202601,'PV1',
               DATE '2025-12-01','MAXIMUM','NONE','Tester',100.0,120.0,20.0,
               0.20,0.833,0.0,1.0),
              ('S2','Berlin Factory','P2','Sensor Module','TT2',202601,'PV1',
               DATE '2025-12-01','NORMAL','NONE','Handler',80.0,100.0,20.0,
               0.25,0.80,0.0,1.0),
              ('S2','Berlin Factory','P2','Sensor Module','TT2',202601,'PV1',
               DATE '2025-12-01','MAXIMUM','NONE','Handler',80.0,130.0,50.0,
               0.625,0.615,0.0,2.0)
            ) AS t(
              site_code,site_name,product_number,product_description,test_type,
              month_key,planning_version_id,plan_as_of_date,capacity_mode,
              retest_type,equipment_type,demand_qty,capacity_qty,gap_qty,gap_pct,
              utilization_pct,investment_need_units,excess_capacity_units
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE srv_actual_output AS
            SELECT * FROM (VALUES
              ('S1','P1','TT1',202601,82.0),
              ('S2','P2','TT2',202601,75.0)
            ) AS t(site_code,product_number,test_type,month_key,actual_passed_qty)
            """
        )
        connection.execute(
            """
            CREATE TABLE srv_demonstrated_capacity AS
            SELECT * FROM (VALUES
              ('S1','P1','TT1',202601,85.0),
              ('S2','P2','TT2',202601,78.0)
            ) AS t(
              site_code,product_number,test_type,month_key,
              demonstrated_capacity_qty
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE srv_resource_constraints AS
            SELECT * FROM (VALUES
              (202601,'PV1','S1','P1','TT1','NORMAL','NONE','POOL-1',
               'ALTERNATIVE_POOL','EQ-1,EQ-2','Tester',1,120.0,100.0,-20.0,
               -0.1667,'CRITICAL'),
              (202601,'PV1','S2','P2','TT2','NORMAL','NONE','EQ-3',
               'DEDICATED','EQ-3','Handler',1,70.0,100.0,30.0,
               0.4286,'EXCESS')
            ) AS t(
              month_key,planning_version_id,site_code,product_number,test_type,
              capacity_mode,retest_type,resource_constraint_id,resource_behavior,
              equipment_id,equipment_type,affected_products,required_resource_hours,
              available_resource_hours,gap_resource_hours,gap_ratio,
              bottleneck_severity
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE srv_gcm_resource_contract AS
            SELECT * FROM (VALUES
              ('S1','P1','TT1','Electrical Test','PV1',202601,'POOL-1','STEP-1',
               'ALTERNATIVE_POOL','EQ-1','Q-1'),
              ('S1','P1','TT1','Electrical Test','PV1',202601,'POOL-1','STEP-1',
               'ALTERNATIVE_POOL','EQ-2','Q-2'),
              ('S2','P2','TT2','Functional Test','PV1',202601,NULL,'STEP-2',
               'DEDICATED','EQ-3','Q-3')
            ) AS t(
              site_code,product_number,test_type,test_category_name,
              planning_version_id,month_key,pool_id,route_step_id,
              resource_behavior,equipment_id,qualification_id
            )
            """
        )
    (tmp_path / "release_current.json").write_text(
        json.dumps(
            {
                "release_id": "release-1",
                "promoted_at": "2026-01-15T00:00:00Z",
                "publications": {
                    "serving": {"run_id": "pipeline-1", "path": str(database)}
                },
            }
        ),
        encoding="utf-8",
    )
    return database


def test_registry_enables_capacity_analysis_after_data_explorer() -> None:
    app_ids = [item.app_id for item in APPLICATIONS]
    index = app_ids.index("data-explorer") + 1
    capacity = APPLICATIONS[index]
    assert capacity.app_id == "capacity-analysis"
    assert capacity.enabled is True
    assert capacity.router_module == "capacity_analysis.backend.main"


def test_health_and_filters_use_full_labels(promoted_serving: Path) -> None:
    health = client.get("/capacity-analysis/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ready"

    response = client.get("/capacity-analysis/api/filters/tactical")
    assert response.status_code == 200
    payload = response.json()
    assert payload["applicable"] == [
        "site",
        "product",
        "test_type",
        "capacity_mode",
        "retest",
        "planning_version",
        "month_from",
        "month_to",
    ]
    assert payload["options"]["site"][0]["label"] == "Austin Factory (S1)"
    assert payload["options"]["product"][0]["label"] == "Router Board (P1)"
    assert payload["options"]["test_type"][0]["label"] == "Electrical Test (TT1)"
    assert {item["value"] for item in payload["options"]["retest"]} == {
        "NONE",
        "TYPE1",
        "TYPE2",
    }


def test_tactical_filters_and_metric_semantics(promoted_serving: Path) -> None:
    response = client.get(
        "/capacity-analysis/api/tactical",
        params={
            "site": "S1",
            "product": "P1",
            "test_type": "TT1",
            "capacity_mode": "NORMAL",
            "retest": "NONE",
            "planning_version": "PV1",
            "month_from": 202601,
            "month_to": 202601,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["kpis"]["demand"] == 100.0
    assert payload["kpis"]["normal_capacity"] == 90.0
    assert payload["kpis"]["maximum_capacity"] == 120.0
    assert payload["kpis"]["actual_output"] == 82.0
    assert payload["kpis"]["demonstrated_capacity"] == 85.0
    assert payload["trend"][0]["actual_output"] == 82.0
    bridge = payload["capacity_loss_waterfall"]
    assert bridge["maximum_capacity"] + bridge["components"][1]["value"] == bridge[
        "normal_capacity"
    ]
    assert bridge["reconciliation_delta"] == 0.0
    assert payload["alternative_resources"][0]["qualified_resources"] == "EQ-1, EQ-2"


def test_capacity_mode_and_retest_values_are_rejected(promoted_serving: Path) -> None:
    assert (
        client.get(
            "/capacity-analysis/api/tactical",
            params={"capacity_mode": "SURGE"},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/capacity-analysis/api/tactical",
            params={"retest": "TYPE3"},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/capacity-analysis/api/tactical",
            params={"month_from": 202613},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/capacity-analysis/api/tactical",
            params={"machine": "EQ-1"},
        ).status_code
        == 422
    )


def test_bottleneck_contract_reports_hours_and_investment(
    promoted_serving: Path,
) -> None:
    response = client.get(
        "/capacity-analysis/api/bottlenecks",
        params={
            "site": "S1",
            "product": "P1",
            "capacity_mode": "NORMAL",
            "retest": "NONE",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    constraint = payload["constraints"][0]
    assert constraint["required_resource_hours"] == 120.0
    assert constraint["available_resource_hours"] == 100.0
    assert constraint["bottleneck_severity"] == "CRITICAL"
    assert constraint["affected_products"] == 1
    assert payload["movement"][0]["gap_resource_hours"] == -20.0
    assert payload["kpis"]["investment_need_units"] == 1


def test_waterfall_reconciliation_formula_is_exact() -> None:
    bridge = reconcile_capacity_waterfall(1_000.25, 850.10)
    assert sum(item.value for item in bridge.components[:2]) == bridge.normal_capacity
    assert bridge.reconciliation_delta == 0.0


def test_not_ready_state_is_clear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAPACITY_TWIN_HOME", str(tmp_path))
    response = client.get("/capacity-analysis/api/tactical")
    assert response.status_code == 503
    assert "not ready" in response.json()["detail"].lower()
