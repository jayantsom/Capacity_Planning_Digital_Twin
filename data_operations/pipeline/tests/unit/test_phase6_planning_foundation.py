"""Gold formula tests for the Phase 6 planning data foundation."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from pathlib import Path

import duckdb
import pandas as pd

from capacity_twin_core.runtime.database_paths import load_config
from data_operations.generator.catalogs.contract_tables import build_routes
from data_operations.generator.generators.planning_foundation import (
    generate_planning_foundation,
)
from data_operations.generator.generators.product_master import generate_product_master
from data_operations.generator.generators.reference_data import (
    generate_equipment_master,
    generate_site_master,
    generate_test_type_master,
)
from data_operations.generator.services.atomic_publication import initialize_raw_databases
from data_operations.pipeline.pipeline.gold.planning_foundation import (
    build_planning_foundation,
)
from data_operations.pipeline.pipeline.gold.serving_views import SERVING_VIEWS


def _source_config(tmp_path: Path) -> dict:
    config = deepcopy(load_config())
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    config["paths"]["raw_sqlite"] = str(raw_dir)
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
    initialize_raw_databases(raw_dir, config)
    generate_planning_foundation(config)
    return config


def _expose_source_tables(connection, config: dict) -> None:
    raw_dir = Path(config["paths"]["raw_sqlite"])
    for database_key in ("demand", "inventory", "machine", "execution", "npi"):
        path = raw_dir / config["databases"]["raw"][database_key]
        with sqlite3.connect(path) as source:
            table_names = [
                row[0]
                for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            for table in table_names:
                if table in {
                    "equipment_master",
                    "machine_execution",
                    "machine_logs",
                    "site_equipment_inventory",
                }:
                    continue
                frame = pd.read_sql_query(f'SELECT * FROM "{table}"', source)
                frame["is_valid"] = True
                connection.register("_source_frame", frame)
                connection.execute(
                    f'CREATE TABLE "slvr_{table}" AS SELECT * FROM _source_frame'
                )
                connection.unregister("_source_frame")
    _, route_steps = build_routes()
    route_steps["is_valid"] = True
    connection.register("_route_steps", route_steps)
    connection.execute("CREATE TABLE slvr_route_step AS SELECT * FROM _route_steps")
    connection.unregister("_route_steps")
    dimensions = {
        "slvr_ref_site": generate_site_master(),
        "slvr_ref_test_type": generate_test_type_master(),
        "slvr_ref_equipment": generate_equipment_master(),
        "slvr_prod_master": generate_product_master(),
    }
    for table_name, frame in dimensions.items():
        frame["is_valid"] = True
        connection.register("_dimension_frame", frame)
        connection.execute(
            f'CREATE TABLE "{table_name}" AS SELECT * FROM _dimension_frame'
        )
        connection.unregister("_dimension_frame")


def test_gold_planning_foundation_reconciles_and_publishes_metrics(tmp_path: Path) -> None:
    config = _source_config(tmp_path)
    with duckdb.connect() as connection:
        _expose_source_tables(connection, config)
        counts = build_planning_foundation(connection)

        assert counts["gold_sop_balance"] > 0
        assert connection.execute(
            "SELECT COUNT(*) FROM gold_sop_balance "
            "WHERE ABS(inventory_balance_variance_ea) > 0.000001"
        ).fetchone()[0] == 0
        assert counts["gold_npi_readiness"] > 0
        assert counts["gold_npi_ramp"] > 0
        assert counts["gold_operations_wip"] > 0
        assert counts["gold_operations_schedule_attainment"] > 0
        assert counts["gold_operations_bottleneck_movement"] > 0
        assert counts["gold_scenario_inputs"] > 0
        assert counts["gold_equipment_cost_reference"] > 0
        phase6_serving = {
            "srv_sop_balance",
            "srv_npi_readiness",
            "srv_npi_ramp",
            "srv_npi_stage_gate",
            "srv_operations_wip",
            "srv_operations_queue",
            "srv_operations_cycle_time",
            "srv_operations_throughput",
            "srv_operations_rework",
            "srv_operations_route_adherence",
            "srv_operations_schedule_attainment",
            "srv_operations_bottleneck_movement",
            "srv_operations_route_flow",
            "srv_scenario_inputs",
            "srv_equipment_cost_reference",
        }
        for table in phase6_serving:
            connection.execute(f'CREATE TABLE "{table}" AS {SERVING_VIEWS[table]}')
            assert connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] > 0
