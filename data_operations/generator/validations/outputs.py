"""Post-generation checks that block publication on unexpected defects."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from capacity_twin_core.data.ownership import RAW_DATABASE_TABLES, assert_raw_tables


def file_checksum(path: Path) -> str:
    """Return a streaming SHA-256 checksum for one generated database."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _scalar(connection: sqlite3.Connection, query: str) -> Any:
    return connection.execute(query).fetchone()[0]


def validate_outputs(raw_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Validate schemas, bounds, dates, identities, and Machine reconciliation."""
    errors: list[str] = []
    row_counts: dict[str, dict[str, int]] = {}
    checksums: dict[str, str] = {}
    database_names = config["databases"]["raw"]

    for database_key, filename in database_names.items():
        path = raw_dir / filename
        if not path.is_file():
            errors.append(f"missing database {database_key}: {filename}")
            continue
        checksums[filename] = file_checksum(path)
        with sqlite3.connect(path) as connection:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            ]
            try:
                assert_raw_tables(set(tables))
            except ValueError as error:
                errors.append(str(error))
            expected_tables = RAW_DATABASE_TABLES[database_key]
            if set(tables) != expected_tables:
                errors.append(
                    f"{filename} tables {sorted(tables)} do not equal "
                    f"{sorted(expected_tables)}"
                )
            row_counts[filename] = {
                table: int(_scalar(connection, f'SELECT COUNT(*) FROM "{table}"'))
                for table in tables
            }
            for table in tables:
                columns = {
                    row[1]
                    for row in connection.execute(f'PRAGMA table_info("{table}")')
                }
                required_metadata = {
                    "source_system_id",
                    "source_company_id",
                    "source_site_id",
                    "source_record_id",
                    "source_batch_id",
                    "extracted_at_utc",
                }
                missing_metadata = sorted(required_metadata - columns)
                if missing_metadata:
                    errors.append(f"{table} is missing source metadata {missing_metadata}")

    execution_path = raw_dir / database_names["execution"]
    parameter_path = raw_dir / database_names["test"]
    log_path = raw_dir / database_names["machine"]
    if execution_path.is_file():
        with sqlite3.connect(execution_path) as connection:
            date_bounds = connection.execute(
                "SELECT MIN(execution_date), MAX(execution_date) FROM machine_execution"
            ).fetchone()
            expected = (
                config["data_generation"]["start_date_actual"],
                config["data_generation"]["end_date_actual"],
            )
            if tuple(date_bounds) != expected:
                errors.append(f"execution date bounds {tuple(date_bounds)} do not equal {expected}")
            if _scalar(
                connection,
                "SELECT COUNT(*) FROM machine_execution WHERE total_qty != passed_qty + failed_qty",
            ):
                errors.append("execution total quantity does not reconcile")
            if _scalar(
                connection,
                "SELECT COUNT(*) FROM machine_execution WHERE yield_avg IS NOT NULL "
                "AND (yield_avg < 0 OR yield_avg > 1)",
            ):
                errors.append("execution yield is outside [0, 1]")
            unexpected_duplicates = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM (
                    SELECT event_id
                    FROM machine_execution
                    GROUP BY event_id
                    HAVING COUNT(*) > 1
                       AND SUM(CASE WHEN noise_rule_id = 'RAW_DUPLICATE_EXECUTION' THEN 1 ELSE 0 END) = 0
                )
                """,
            )
            if unexpected_duplicates:
                errors.append("execution contains undeclared duplicate events")

    if execution_path.is_file() and parameter_path.is_file():
        with sqlite3.connect(parameter_path) as connection:
            connection.execute("ATTACH DATABASE ? AS execution_db", (str(execution_path),))
            mismatches = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM machine_test_param p
                LEFT JOIN execution_db.machine_execution e
                  ON e.record_id = p.execution_record_id
                WHERE e.record_id IS NULL
                   OR p.total_qty != e.total_qty
                   OR p.first_pass_qty != e.passed_qty
                   OR p.first_fail_qty != e.failed_qty
                """,
            )
            if mismatches:
                errors.append(f"{mismatches} parameter rows do not reconcile to execution")

    if execution_path.is_file() and log_path.is_file():
        with sqlite3.connect(log_path) as connection:
            connection.execute("ATTACH DATABASE ? AS execution_db", (str(execution_path),))
            orphan_logs = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM machine_logs l
                LEFT JOIN execution_db.machine_execution e
                  ON e.record_id = l.execution_record_id
                WHERE e.record_id IS NULL
                """,
            )
            if orphan_logs:
                errors.append(f"{orphan_logs} logs do not reference execution events")

    budget_pairs = (
        ("execution", "machine_execution", "max_execution_rows"),
        ("test", "machine_test_param", "max_test_parameter_rows"),
        ("machine", "machine_logs", "max_log_rows"),
    )
    for database_key, table, cap_name in budget_pairs:
        count = row_counts.get(database_names[database_key], {}).get(table, 0)
        if count > config["local_16gb"][cap_name]:
            errors.append(f"{table} row count {count:,} exceeds {cap_name}")

    demand_path = raw_dir / database_names["demand"]
    inventory_path = raw_dir / database_names["inventory"]
    if demand_path.is_file() and inventory_path.is_file():
        with sqlite3.connect(inventory_path) as connection:
            connection.execute("ATTACH DATABASE ? AS demand_db", (str(demand_path),))
            balance_errors = _scalar(
                connection,
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
                """,
            )
            if balance_errors:
                errors.append(f"{balance_errors} source inventory balances do not reconcile")
            negative_backlog = _scalar(
                connection,
                "SELECT COUNT(*) FROM demand_db.backlog_position WHERE open_quantity_ea < 0",
            )
            if negative_backlog:
                errors.append("backlog positions contain negative quantities")
            inventory_bounds = connection.execute(
                "SELECT MIN(position_date), MAX(position_date) "
                "FROM material_inventory_position"
            ).fetchone()
            if inventory_bounds[0] < config["data_generation"]["start_date_actual"]:
                errors.append("inventory positions begin before the configured actual start")
            if inventory_bounds[1] > config["data_generation"]["end_date_forecast"]:
                errors.append("inventory positions exceed the configured forecast end")
            plan_bounds = connection.execute(
                "SELECT MIN(month_key), MAX(month_key) "
                "FROM demand_db.constrained_production_plan"
            ).fetchone()
            expected_plan_bounds = (
                int(config["data_generation"]["start_date_actual"][:7].replace("-", "")),
                int(config["data_generation"]["end_date_forecast"][:7].replace("-", "")),
            )
            if tuple(plan_bounds) != expected_plan_bounds:
                errors.append(
                    f"production plan month bounds {tuple(plan_bounds)} "
                    f"do not equal {expected_plan_bounds}"
                )
            dated_source_bounds = (
                connection.execute(
                    "SELECT MIN(order_date), MAX(confirmed_delivery_date) "
                    "FROM demand_db.customer_order"
                ).fetchone()
                + connection.execute(
                    "SELECT MIN(expected_receipt_date), MAX(expected_receipt_date) "
                    "FROM inbound_receipt"
                ).fetchone()
                + connection.execute(
                    "SELECT MIN(shipment_date), MAX(shipment_date) FROM shipment"
                ).fetchone()
            )
            if min(dated_source_bounds) < config["data_generation"]["start_date_actual"]:
                errors.append("S&OP facts begin before the configured actual start")
            if max(dated_source_bounds) > config["data_generation"]["end_date_forecast"]:
                errors.append("S&OP facts exceed the configured forecast end")
            for table, key_columns in (
                ("safety_stock_policy", ("site_code", "product_number")),
                ("service_target", ("site_code", "product_number", "customer_segment")),
            ):
                keys = " AND ".join(f"left_row.{key} = right_row.{key}" for key in key_columns)
                overlaps = _scalar(
                    connection,
                    f"""
                    SELECT COUNT(*)
                    FROM {table} left_row
                    JOIN {table} right_row
                      ON {keys}
                     AND left_row.rowid < right_row.rowid
                     AND left_row.effective_start_date <= right_row.effective_end_date
                     AND right_row.effective_start_date <= left_row.effective_end_date
                    """,
                )
                if overlaps:
                    errors.append(f"{table} contains overlapping effective intervals")

    if execution_path.is_file():
        with sqlite3.connect(execution_path) as connection:
            movement_errors = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM lot_route_movement_event
                WHERE queue_entry_at > queue_exit_at
                   OR queue_exit_at > movement_event_at
                   OR input_quantity_ea < 0
                   OR output_quantity_ea < 0
                   OR output_quantity_ea > input_quantity_ea
                   OR disposition_code NOT IN ('PASS', 'REWORK', 'SCRAP')
                """,
            )
            if movement_errors:
                errors.append(f"{movement_errors} movement events violate source contracts")
            orphan_rework = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM lot_route_movement_event event
                LEFT JOIN lot_route_movement_event linked
                  ON event.rework_link_event_id = linked.movement_event_id
                WHERE event.rework_link_event_id IS NOT NULL
                  AND linked.movement_event_id IS NULL
                """,
            )
            if orphan_rework:
                errors.append(f"{orphan_rework} rework links are orphaned")
            movement_bounds = connection.execute(
                """
                SELECT MIN(substr(movement_event_at, 1, 10)),
                       MAX(substr(movement_event_at, 1, 10))
                FROM lot_route_movement_event
                """
            ).fetchone()
            if movement_bounds[0] < config["data_generation"]["start_date_actual"]:
                errors.append("movement events begin before the configured actual start")
            if movement_bounds[1] > config["data_generation"]["end_date_actual"]:
                errors.append("movement events exceed the configured actual cutoff")

    npi_path = raw_dir / database_names["npi"]
    if npi_path.is_file():
        with sqlite3.connect(npi_path) as connection:
            invalid_program_interval = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM npi_program
                WHERE effective_start_date > effective_end_date
                   OR planned_launch_date > effective_end_date
                """,
            )
            if invalid_program_interval:
                errors.append("NPI programs contain invalid effective intervals")
            duplicate_status_sequence = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM (
                    SELECT program_id, status_sequence
                    FROM npi_status_history
                    GROUP BY program_id, status_sequence
                    HAVING COUNT(*) > 1
                )
                """,
            )
            if duplicate_status_sequence:
                errors.append("NPI status history sequence is not unique")

    machine_path = raw_dir / database_names["machine"]
    if machine_path.is_file():
        with sqlite3.connect(machine_path) as connection:
            cost_overlaps = _scalar(
                connection,
                """
                SELECT COUNT(*)
                FROM equipment_cost_reference left_row
                JOIN equipment_cost_reference right_row
                  ON left_row.equipment_id = right_row.equipment_id
                 AND left_row.rowid < right_row.rowid
                 AND left_row.effective_start_date <= right_row.effective_end_date
                 AND right_row.effective_start_date <= left_row.effective_end_date
                """,
            )
            if cost_overlaps:
                errors.append("equipment cost references contain overlapping intervals")

    cap_checks = (
        ("demand", "customer_order", "max_sop_rows"),
        ("demand", "backlog_position", "max_sop_rows"),
        ("inventory", "material_inventory_position", "max_sop_rows"),
        ("execution", "lot_route_movement_event", "max_operations_movement_rows"),
    )
    for database_key, table, cap_name in cap_checks:
        count = row_counts.get(database_names[database_key], {}).get(table, 0)
        if count > config["local_16gb"][cap_name]:
            errors.append(f"{table} row count {count:,} exceeds {cap_name}")
    npi_rows = sum(row_counts.get(database_names["npi"], {}).values())
    if npi_rows > config["local_16gb"]["max_npi_rows"]:
        errors.append(f"NPI row count {npi_rows:,} exceeds max_npi_rows")

    report = {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "warnings": [],
        "row_counts": row_counts,
        "checksums": checksums,
    }
    if errors:
        raise ValueError("Output validation failed:\n- " + "\n- ".join(errors))
    return report
