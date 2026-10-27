"""Post-generation checks that block publication on unexpected defects."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

from capacity_twin_core.data.ownership import assert_raw_tables


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
            row_counts[filename] = {
                table: int(_scalar(connection, f'SELECT COUNT(*) FROM "{table}"'))
                for table in tables
            }

    execution_path = raw_dir / database_names["machine_execution"]
    parameter_path = raw_dir / database_names["test_x_parameter"]
    log_path = raw_dir / database_names["machine_logs"]
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
        ("machine_execution", "machine_execution", "max_execution_rows"),
        ("test_x_parameter", "machine_test_param", "max_test_parameter_rows"),
        ("machine_logs", "machine_logs", "max_log_rows"),
    )
    for database_key, table, cap_name in budget_pairs:
        count = row_counts.get(database_names[database_key], {}).get(table, 0)
        if count > config["local_16gb"][cap_name]:
            errors.append(f"{table} row count {count:,} exceeds {cap_name}")

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
