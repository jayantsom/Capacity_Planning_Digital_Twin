"""A tiny all-database build that avoids the production-sized date range."""

import json
import sqlite3
from copy import deepcopy
from pathlib import Path

from capacity_twin_core.runtime.database_paths import load_config
from data_operations.generator.generators.run_all_generators import run_all


def test_tiny_candidate_validates_before_publish(tmp_path: Path) -> None:
    config = deepcopy(load_config())
    config["paths"]["runtime_home"] = str(tmp_path)
    config["paths"]["raw_sqlite"] = str(tmp_path / "published")
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

    published = tmp_path / "published"
    assert {path.name for path in published.glob("*.db")} == set(
        config["databases"]["raw"].values()
    )
    manifests = list((tmp_path / "artifacts").glob("*/manifest.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text(encoding="utf-8"))["validation"]["status"] == "passed"
    inventory_db = published / config["databases"]["raw"]["site_equipment_inventory"]
    with sqlite3.connect(inventory_db) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM site_equipment_inventory"
        ).fetchone()[0] <= config["local_16gb"]["max_site_resource_relationships"]
