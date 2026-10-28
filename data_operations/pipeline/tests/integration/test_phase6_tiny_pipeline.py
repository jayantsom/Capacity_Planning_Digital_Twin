"""Isolated end-to-end publication checks for the planning data foundation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import duckdb
import pytest

from capacity_twin_core.runtime.database_paths import load_config
from data_operations.generator.generators.run_all_generators import run_all
from data_operations.pipeline.runner import run_pipeline


def test_phase6_serving_publication_reconciles(tmp_path: Path) -> None:
    pytest.importorskip("pyspark")
    config = deepcopy(load_config())
    config["paths"]["runtime_home"] = str(tmp_path)
    config["data_generation"].update(
        {
            "start_date_actual": "2026-09-01",
            "end_date_actual": "2026-10-31",
            "start_date_forecast": "2026-11-01",
            "end_date_forecast": "2026-12-31",
            "plan_as_of_dates": ["2026-10-31"],
            "volume": "low",
        }
    )
    run_all(config)
    candidate = run_pipeline(config)

    serving_path = candidate.paths.database("serving")
    with duckdb.connect(str(serving_path), read_only=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM srv_sop_balance").fetchone()[0] > 0
        assert connection.execute(
            "SELECT COUNT(*) FROM srv_sop_balance "
            "WHERE ABS(inventory_balance_variance_ea) > 0.000001"
        ).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM srv_npi_readiness").fetchone()[0] > 0
        assert connection.execute("SELECT COUNT(*) FROM srv_npi_ramp").fetchone()[0] > 0
        assert connection.execute("SELECT COUNT(*) FROM srv_operations_queue").fetchone()[0] > 0
        assert connection.execute(
            "SELECT COUNT(*) FROM srv_operations_schedule_attainment"
        ).fetchone()[0] > 0
        assert connection.execute("SELECT COUNT(*) FROM srv_scenario_inputs").fetchone()[0] > 0
        assert connection.execute(
            "SELECT COUNT(*) FROM srv_equipment_cost_reference"
        ).fetchone()[0] > 0
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT site_code, product_number, month_key
                FROM srv_ml_feature_store
                WHERE is_actual = 1
                GROUP BY site_code, product_number, month_key
                HAVING COUNT(DISTINCT demand_qty) > 1
            )
            """
        ).fetchone()[0] == 0
