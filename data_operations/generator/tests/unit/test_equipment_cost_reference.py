"""Focused invariants for equipment cost source generation."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from pathlib import Path

from capacity_twin_core.runtime.database_paths import load_config
from data_operations.generator.generators.equipment_cost_reference import (
    generate_equipment_cost_reference,
)
from data_operations.generator.generators.reference_data import FIXTURES, SYSTEMS
from data_operations.generator.services.atomic_publication import (
    initialize_raw_databases,
)


def test_equipment_cost_generation_is_complete_and_effective_dated(
    tmp_path: Path,
) -> None:
    config = deepcopy(load_config())
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    config["paths"]["raw_sqlite"] = str(raw_dir)
    initialize_raw_databases(raw_dir, config)

    frame = generate_equipment_cost_reference(config)

    assert len(frame) == len(SYSTEMS) + len(FIXTURES)
    assert frame["equipment_id"].is_unique
    assert set(frame["cost_status"]) == {"APPROVED"}
    assert set(frame["effective_start_date"]) == {
        config["data_generation"]["start_date_actual"]
    }
    assert set(frame["effective_end_date"]) == {
        config["data_generation"]["end_date_forecast"]
    }
    with sqlite3.connect(raw_dir / "raw_machine.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM equipment_cost_reference"
        ).fetchone()[0] == len(frame)
