"""Focused invariants for bounded Phase 6 source generation."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from pathlib import Path

from capacity_twin_core.runtime.database_paths import load_config
from data_operations.generator.generators.planning_foundation import (
    generate_planning_foundation,
)
from data_operations.generator.services.atomic_publication import initialize_raw_databases


def _config(tmp_path: Path) -> dict:
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
    return config


def test_planning_generation_is_bounded_and_reconciled(tmp_path: Path) -> None:
    config = _config(tmp_path)
    counts = generate_planning_foundation(config)

    assert counts["customer_order"] <= config["local_16gb"]["max_sop_rows"]
    assert (
        counts["lot_route_movement_event"]
        <= config["local_16gb"]["max_operations_movement_rows"]
    )
    raw_dir = Path(config["paths"]["raw_sqlite"])
    with sqlite3.connect(raw_dir / "raw_inventory.db") as connection:
        connection.execute(
            "ATTACH DATABASE ? AS demand_db",
            (str(raw_dir / "raw_demand.db"),),
        )
        mismatch = connection.execute(
            """
            SELECT COUNT(*)
            FROM material_inventory_position inventory
            JOIN demand_db.constrained_production_plan production
              ON inventory.site_code = production.site_code
             AND inventory.product_number = production.product_number
             AND CAST(strftime('%Y%m', inventory.position_date) AS INTEGER)
                 = production.month_key
            JOIN inbound_receipt receipt
              ON inventory.site_code = receipt.site_code
             AND inventory.product_number = receipt.product_number
             AND strftime('%Y%m', inventory.position_date)
                 = strftime('%Y%m', receipt.expected_receipt_date)
            JOIN shipment
              ON inventory.site_code = shipment.site_code
             AND inventory.product_number = shipment.product_number
             AND strftime('%Y%m', inventory.position_date)
                 = strftime('%Y%m', shipment.shipment_date)
            WHERE inventory.beginning_inventory_quantity_ea
                + production.constrained_production_quantity_ea
                + receipt.received_quantity_ea
                - shipment.shipped_quantity_ea
                != inventory.on_hand_quantity_ea
            """
        ).fetchone()[0]
        assert mismatch == 0
        assert connection.execute(
            "SELECT MIN(position_date), MAX(position_date) "
            "FROM material_inventory_position"
        ).fetchone() == ("2026-09-30", "2026-12-31")
        assert connection.execute(
            "SELECT MIN(expected_receipt_date), MAX(expected_receipt_date) "
            "FROM inbound_receipt"
        ).fetchone() == ("2026-09-09", "2026-12-09")


def test_movement_events_are_ordered_and_rework_links_resolve(tmp_path: Path) -> None:
    config = _config(tmp_path)
    generate_planning_foundation(config)

    path = Path(config["paths"]["raw_sqlite"]) / "raw_execution.db"
    with sqlite3.connect(path) as connection:
        movement_bounds = connection.execute(
            "SELECT MIN(substr(movement_event_at, 1, 10)), "
            "MAX(substr(movement_event_at, 1, 10)) "
            "FROM lot_route_movement_event"
        ).fetchone()
        assert movement_bounds[0] >= "2026-09-01"
        assert movement_bounds[1] <= "2026-10-31"
        assert connection.execute(
            """
            SELECT COUNT(*) FROM lot_route_movement_event
            WHERE queue_entry_at > queue_exit_at
               OR queue_exit_at > movement_event_at
               OR output_quantity_ea > input_quantity_ea
            """
        ).fetchone()[0] == 0
        assert connection.execute(
            """
            SELECT COUNT(*)
            FROM lot_route_movement_event event
            LEFT JOIN lot_route_movement_event linked
              ON event.rework_link_event_id = linked.movement_event_id
            WHERE event.rework_link_event_id IS NOT NULL
              AND linked.movement_event_id IS NULL
            """
        ).fetchone()[0] == 0
