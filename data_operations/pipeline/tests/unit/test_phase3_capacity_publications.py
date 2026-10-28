"""Golden contracts for Phase 3 capacity and publication ownership."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from data_operations.pipeline.pipeline.bronze.schema import BRONZE_CONFIGS
from data_operations.pipeline.pipeline.gold.analytics import (
    build_actual_capacity,
    build_demonstrated_capacity,
)
from data_operations.pipeline.pipeline.gold.capacity_math import (
    _build_workload_resource_scenario_table,
    compute_capacity_for_mode,
)
from data_operations.pipeline.pipeline.gold.serving_views import (
    SERVING_VIEWS,
    build_serving_views,
)
from decision_intelligence import publication as ml_publication
from decision_intelligence.ml_support import ML_OUTPUT_NAME_MAP, file_sha256


def _capacity_input() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "gcm_pk": "g1",
                "site_code": "S",
                "factory_code": "F",
                "month_key": 202611,
                "planning_version_id": "plan-2026-10-31",
                "product_number": "P",
                "product_family": "Family",
                "platform": "Platform",
                "test_type": "ICT",
                "test_category_id": "CAT",
                "equipment_id": "SYS-1",
                "equipment_type": "TEST_SYSTEM",
                "resource_behavior": "MULTI_DUT",
                "route_id": "R",
                "route_step_id": "R-10",
                "route_step_sequence": 10,
                "route_step_demand_qty": 19_200.0,
                "qualification_id": "Q",
                "pool_id": "POOL-ICT",
                "pool_behavior": "ALTERNATIVE_POOL",
                "tester_channels": 4,
                "enabled_licensed_ports": 4,
                "tester_fixture_slots": 4,
                "fixture_cavities": 4,
                "handler_sockets": 4,
                "fixtures_required_per_system": 1,
                "parallel_efficiency": 1.0,
                "target_test_time_sec": 60.0,
                "governed_cycle_time_sec": 60.0,
                "target_yield": 0.90,
                "utilization_rate": 1.0,
                "working_days_normal": 20,
                "shifts_per_day_normal": 1,
                "hours_per_shift_normal": 8,
                "working_days_max": 22,
                "shifts_per_day_max": 2,
                "hours_per_shift_max": 8,
                "allowance_pct": 0.0,
                "productivity_pct": 1.0,
                "equip_qty_available": 1,
                "effective_demand_qty": 19_200.0,
            }
        ]
    )


def test_bronze_contract_covers_all_source_tables() -> None:
    assert len(BRONZE_CONFIGS) == 18
    assert {config.source_table for config in BRONZE_CONFIGS} >= {
        "manufacturer_master",
        "product_bom",
        "product_route",
        "route_step",
        "site_product_source",
    }


def test_layer_manifests_have_exact_retained_object_counts() -> None:
    silver = importlib.import_module("data_operations.pipeline.steps.2_silver")
    gold = importlib.import_module("data_operations.pipeline.steps.3_gold")

    assert len(silver.REQUIRED_TABLES) == 22
    assert len(gold.REQUIRED_TABLES) == 14
    assert len(SERVING_VIEWS) == 19
    assert len(ML_OUTPUT_NAME_MAP) + 1 == 12  # model registry is created at publication


def test_capacity_modes_and_all_retest_modes_are_distinct() -> None:
    source = _capacity_input()
    normal_none = compute_capacity_for_mode(source, "NORMAL", "NONE").iloc[0]
    normal_type1 = compute_capacity_for_mode(source, "NORMAL", "TYPE1").iloc[0]
    normal_type2 = compute_capacity_for_mode(source, "NORMAL", "TYPE2").iloc[0]
    maximum_none = compute_capacity_for_mode(source, "MAXIMUM", "NONE").iloc[0]

    assert normal_none["retest_type"] == "NONE"
    assert normal_none["capacity_qty"] > normal_type1["capacity_qty"]
    assert normal_none["capacity_qty"] > normal_type2["capacity_qty"]
    assert maximum_none["capacity_mode"] == "MAXIMUM"
    assert maximum_none["capacity_qty"] > normal_none["capacity_qty"]
    assert normal_none["effective_parallel_duts"] == pytest.approx(4.0)
    assert normal_none["route_step_id"] == "R-10"


def test_alternative_resource_workload_conserves_route_step_demand() -> None:
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE gold_cap_normal (
                site_code VARCHAR, month_key INTEGER, planning_version_id VARCHAR,
                product_number VARCHAR, route_step_id VARCHAR, test_type VARCHAR,
                capacity_mode VARCHAR, retest_type VARCHAR, resource_behavior VARCHAR,
                pool_id VARCHAR, equipment_id VARCHAR, equipment_type VARCHAR,
                route_step_demand_qty DOUBLE, workload_seconds DOUBLE,
                workload_resource_hours DOUBLE, available_resource_hours DOUBLE,
                capacity_qty DOUBLE
            )
            """
        )
        connection.execute(
            """
            INSERT INTO gold_cap_normal VALUES
              ('S', 202611, 'V', 'P', 'STEP', 'ICT', 'NORMAL', 'NONE',
               'ALTERNATIVE_POOL', 'POOL', 'M1', 'SYSTEM', 100, 1800, .5, 10, 1000),
              ('S', 202611, 'V', 'P', 'STEP', 'ICT', 'NORMAL', 'NONE',
               'ALTERNATIVE_POOL', 'POOL', 'M2', 'SYSTEM', 100, 1800, .5, 10, 1000)
            """
        )
        connection.execute(
            "CREATE TABLE gold_cap_maximum AS SELECT * FROM gold_cap_normal WHERE false"
        )
        assert _build_workload_resource_scenario_table(connection) == 1
        row = connection.execute(
            """
            SELECT route_step_demand_qty, required_resource_hours,
                   available_resource_hours, declared_mix_capacity_qty
            FROM gold_resource_scenarios
            """
        ).fetchone()
    assert row == (100.0, 1.0, 20.0, None)


def test_actual_output_has_no_planning_version_and_demo_is_not_double_counted() -> None:
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE slvr_machine_execution AS
            SELECT * FROM (
              VALUES
                ('F','S','P','CAT','ICT',202609,90,10,100,.90,.90,60,5,50,100,true),
                ('F','S','P','CAT','ICT',202610,95,5,100,.95,.95,55,5,55,80,true)
            ) source(
              factory_code,site_code,product_number,test_category_id,test_type,
              month_key,passed_qty_sum,failed_qty_sum,total_qty_sum,yield_avg,
              final_test_yield_avg,test_duration_avg,handling_time_avg,
              actual_throughput,equipment_downtime_avg,is_valid
            )
            """
        )
        assert build_actual_capacity(connection) == 2
        assert build_demonstrated_capacity(connection) == 2
        actual_columns = {
            row[0] for row in connection.execute("DESCRIBE gold_cap_actual").fetchall()
        }
        demonstrated = connection.execute(
            """
            SELECT formula_id, excludes_future_actuals, loss_factors_not_reapplied,
                   demonstrated_capacity_qty
            FROM gold_demonstrated_capacity
            WHERE month_key = 202610
            """
        ).fetchone()
    assert "planning_version_id" not in actual_columns
    assert demonstrated[:3] == (
        "TRAILING_3_MONTH_MEAN_ACTUAL_OUTPUT",
        True,
        True,
    )
    assert demonstrated[3] == pytest.approx(92.5)


def test_serving_and_ml_publications_own_only_their_prefixes(monkeypatch) -> None:
    from data_operations.pipeline.pipeline.gold import serving_views

    monkeypatch.setattr(serving_views, "SERVING_VIEWS", {"srv_contract": "SELECT 1 AS value"})
    with duckdb.connect() as connection:
        assert build_serving_views(connection) == 1
        objects = connection.execute(
            """
            SELECT table_name, table_type FROM information_schema.tables
            WHERE table_catalog = current_database()
            """
        ).fetchall()
    assert objects == [("srv_contract", "BASE TABLE")]
    assert all(name.startswith("ml_") for name in ML_OUTPUT_NAME_MAP.values())


def test_release_pointer_switches_only_with_compatible_ml(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CAPACITY_TWIN_HOME", str(tmp_path))
    pipeline_run = "pipeline-1"
    pipeline_root = tmp_path / "artifacts" / pipeline_run
    pipeline_root.mkdir(parents=True)
    files = {}
    for layer in ("bronze", "silver", "gold", "serving"):
        database = pipeline_root / f"{layer}.duckdb"
        with duckdb.connect(str(database)) as connection:
            connection.execute(f"CREATE TABLE {layer}_ready(value INTEGER)")
        files[database.name] = {"sha256": file_sha256(database)}
    pipeline_manifest = {
        "source_bundle_run_id": "source-1",
        "source_bundle_checksum": "source-checksum",
        "source_bundle_manifest": str(tmp_path / "source-manifest.json"),
        "files": files,
    }
    pipeline_manifest_path = pipeline_root / "manifest.json"
    pipeline_manifest_path.write_text(json.dumps(pipeline_manifest), encoding="utf-8")
    (tmp_path / "current.json").write_text(
        json.dumps(
            {"active_run_id": pipeline_run, "manifest": str(pipeline_manifest_path)}
        ),
        encoding="utf-8",
    )

    candidate_root = tmp_path / ".staging" / "ml-test"
    candidate_root.mkdir(parents=True)
    candidate_database = candidate_root / "ml.duckdb"
    with duckdb.connect(str(candidate_database)) as connection:
        connection.execute("CREATE TABLE ml_example(value INTEGER)")
    models = candidate_root / "models"
    models.mkdir()
    reference = tmp_path / "reference.duckdb"
    mapping = tmp_path / "mapping.duckdb"
    for path in (reference, mapping):
        with duckdb.connect(str(path)):
            pass
    serving = pipeline_root / "serving.duckdb"
    candidate = ml_publication.PublicationCandidate(
        run_id="ml-test",
        root=candidate_root,
        database=candidate_database,
        models=models,
        source_sha256=file_sha256(serving),
        input_paths={
            "serving": serving,
            "reference": reference,
            "mapping": mapping,
        },
        input_checksums={
            "serving": file_sha256(serving),
            "reference": file_sha256(reference),
            "mapping": file_sha256(mapping),
        },
        pipeline_run_id=pipeline_run,
        source_run_id="source-1",
        previous_results={},
    )
    assert not (tmp_path / "release_current.json").exists()
    ml_publication.publish_candidate(candidate, {1: {"status": "OK"}})
    release = json.loads(
        (tmp_path / "release_current.json").read_text(encoding="utf-8")
    )
    assert release["publications"]["serving"]["run_id"] == pipeline_run
    assert release["ml"]["input_pipeline_run_id"] == pipeline_run
    assert release["ml"]["input_checksums"]["serving"] == file_sha256(serving)
