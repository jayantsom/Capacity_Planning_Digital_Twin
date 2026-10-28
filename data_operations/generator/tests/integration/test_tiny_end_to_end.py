"""A tiny all-database build that avoids the production-sized date range."""

import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import duckdb

from capacity_twin_core.data.ownership import SOURCE_RAW_TABLES
from capacity_twin_core.runtime.database_paths import load_config
from data_operations.generator.generators.run_all_generators import run_all


def test_tiny_candidate_validates_before_publish(tmp_path: Path) -> None:
    config = deepcopy(load_config())
    config["paths"]["runtime_home"] = str(tmp_path)
    config["data_generation"].update(
        {
            "start_date_actual": "2026-10-26",
            "end_date_actual": "2026-10-31",
            "start_date_forecast": "2026-11-01",
            "end_date_forecast": "2026-12-31",
            "plan_as_of_dates": ["2026-10-31"],
            "volume": "low",
        }
    )

    run_all(config)

    pointer = json.loads((tmp_path / "source_current.json").read_text(encoding="utf-8"))
    published = tmp_path / pointer["raw_directory"]
    assert {path.name for path in published.glob("*.db")} == set(
        config["databases"]["raw"].values()
    )
    manifests = list(
        (tmp_path / "source_bundles").glob("*/source_bundle_manifest.json")
    )
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text(encoding="utf-8"))["validation"]["status"] == "passed"
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["source_run_id"] == pointer["source_run_id"]
    assert manifest["bundle_checksum"] == pointer["bundle_checksum"]
    assert len(manifest["files"]) == 11
    assert all(
        {
            "sha256",
            "schema_version",
            "table_count",
            "tables",
            "path",
        }
        <= set(details)
        for details in manifest["files"].values()
    )
    raw_tables = {
        table
        for details in manifest["files"].values()
        if details["role"] == "raw"
        for table in details["tables"]
    }
    assert raw_tables == SOURCE_RAW_TABLES
    assert manifest["files"]["raw_inventory.db"]["table_count"] == 5
    assert manifest["files"]["raw_npi.db"]["table_count"] == 11
    assert manifest["files"]["raw_demand.db"]["tables"]["customer_order"] > 0
    assert manifest["files"]["raw_execution.db"]["tables"]["lot_route_movement_event"] > 0
    for name, schema, table in (
        ("reference.duckdb", "meta", "reference_publication"),
        ("mapping.duckdb", "meta", "mapping_publication"),
    ):
        with duckdb.connect(str(tmp_path / manifest["files"][name]["path"])) as connection:
            assert connection.execute(
                f'SELECT source_run_id FROM "{schema}"."{table}"'
            ).fetchone()[0] == pointer["source_run_id"]
    inventory_db = published / config["databases"]["raw"]["machine"]
    with sqlite3.connect(inventory_db) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                'PRAGMA table_info("site_equipment_inventory")'
            )
        }
        assert {
            "source_system_id",
            "source_company_id",
            "source_site_id",
            "source_record_id",
            "source_batch_id",
            "extracted_at_utc",
        } <= columns
        assert connection.execute(
            "SELECT COUNT(*) FROM site_equipment_inventory"
        ).fetchone()[0] <= config["local_16gb"]["max_site_resource_relationships"]
