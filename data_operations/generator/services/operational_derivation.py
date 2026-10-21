"""Derive parameter and log facts from canonical Machine execution rows."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from data_operations.generator.rules.determinism import stable_id


def derive_test_parameters(execution_db: Path, output_db: Path) -> int:
    """Create one reconciled test-parameter row per execution record."""
    with sqlite3.connect(execution_db) as source, sqlite3.connect(output_db) as target:
        source.row_factory = sqlite3.Row
        target.execute("DROP TABLE IF EXISTS machine_test_param")
        target.execute(
            """
            CREATE TABLE machine_test_param (
                parameter_record_id TEXT PRIMARY KEY,
                execution_record_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                factory_code TEXT NOT NULL,
                site_code TEXT NOT NULL,
                product_number TEXT NOT NULL,
                test_category_id TEXT NOT NULL,
                test_type TEXT NOT NULL,
                execution_date TEXT NOT NULL,
                month_key INTEGER NOT NULL,
                first_pass_qty INTEGER NOT NULL,
                first_fail_qty INTEGER NOT NULL,
                total_qty INTEGER NOT NULL,
                first_pass_yield REAL NOT NULL,
                test_x_parameter REAL NOT NULL,
                retest_times_avg REAL NOT NULL,
                retest_times_type1 REAL NOT NULL,
                retest_times_type2 REAL NOT NULL,
                yield_retest_1 REAL NOT NULL,
                yield_retest_2_plus REAL NOT NULL,
                noise_rule_id TEXT,
                data_provenance TEXT NOT NULL
            )
            """
        )
        insert_sql = (
            "INSERT INTO machine_test_param VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        )
        count = 0
        cursor = source.execute(
            """
            SELECT record_id, event_id, factory_code, site_code, product_number,
                   test_category_id, test_type, execution_date, month_key,
                   passed_qty, failed_qty, total_qty, noise_rule_id
            FROM machine_execution
            ORDER BY execution_date, site_code, product_number, test_type, record_id
            """
        )
        while batch := cursor.fetchmany(10_000):
            rows = []
            for row in batch:
                total = int(row["total_qty"])
                passed = int(row["passed_qty"])
                failed = int(row["failed_qty"])
                first_pass_yield = passed / total
                yield_retest_1 = min(0.99, 0.72 + first_pass_yield * 0.20)
                yield_retest_2 = min(0.995, 0.88 + first_pass_yield * 0.10)
                rows.append(
                    (
                        stable_id("parameter", row["record_id"]),
                        row["record_id"],
                        row["event_id"],
                        row["factory_code"],
                        row["site_code"],
                        row["product_number"],
                        row["test_category_id"],
                        row["test_type"],
                        row["execution_date"],
                        row["month_key"],
                        passed,
                        failed,
                        total,
                        round(first_pass_yield, 6),
                        0.75,
                        round(1 + failed / total, 6),
                        2.0,
                        round((1 - yield_retest_1 + yield_retest_2) / yield_retest_2, 6),
                        round(yield_retest_1, 6),
                        round(yield_retest_2, 6),
                        row["noise_rule_id"],
                        "DERIVED_FROM_MACHINE_EXECUTION",
                    )
                )
            target.executemany(insert_sql, rows)
            count += len(rows)
        target.execute(
            "CREATE UNIQUE INDEX idx_param_execution_record ON machine_test_param(execution_record_id)"
        )
        return count


def derive_logs(execution_db: Path, output_db: Path) -> int:
    """Create bounded excursions that reference real execution records."""
    with sqlite3.connect(execution_db) as source, sqlite3.connect(output_db) as target:
        source.row_factory = sqlite3.Row
        target.execute("DROP TABLE IF EXISTS machine_logs")
        target.execute(
            """
            CREATE TABLE machine_logs (
                log_event_id TEXT PRIMARY KEY,
                execution_record_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                factory_code TEXT NOT NULL,
                site_code TEXT NOT NULL,
                product_number TEXT NOT NULL,
                test_category_id TEXT NOT NULL,
                test_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                error_code TEXT NOT NULL,
                error_description TEXT,
                severity TEXT NOT NULL,
                log_ts TEXT NOT NULL,
                execution_date TEXT NOT NULL,
                month_key INTEGER NOT NULL,
                noise_rule_id TEXT,
                data_provenance TEXT NOT NULL
            )
            """
        )
        candidates = source.execute(
            """
            SELECT record_id, event_id, factory_code, site_code, product_number,
                   test_category_id, test_type, execution_date, month_key,
                   yield_avg, test_duration_avg_sec, equipment_downtime_avg_sec,
                   noise_rule_id
            FROM machine_execution
            WHERE yield_avg < 0.82
               OR yield_avg IS NULL
               OR equipment_downtime_avg_sec > 3600
               OR test_duration_avg_sec > 1800
            ORDER BY execution_date, site_code, product_number, test_type, record_id
            """
        )
        rows = []
        for row in candidates:
            if row["yield_avg"] is None:
                code, description, severity = "E-004", "Sensor data missing or invalid", "ERROR"
            elif row["equipment_downtime_avg_sec"] > 3600:
                code, description, severity = "E-002", "Equipment downtime event detected", "ERROR"
            elif row["test_duration_avg_sec"] > 1800:
                code, description, severity = "E-003", "Test duration anomaly detected", "WARN"
            else:
                code, description, severity = "E-001", "Yield excursion below threshold", "ERROR"
            rows.append(
                (
                    stable_id("log", row["record_id"], code),
                    row["record_id"],
                    row["event_id"],
                    row["factory_code"],
                    row["site_code"],
                    row["product_number"],
                    row["test_category_id"],
                    row["test_type"],
                    f"POOL-{row['test_type']}",
                    code,
                    description,
                    severity,
                    f"{row['execution_date']}T12:00:00",
                    row["execution_date"],
                    row["month_key"],
                    row["noise_rule_id"],
                    "DERIVED_FROM_MACHINE_EXECUTION",
                )
            )
        target.executemany(
            "INSERT INTO machine_logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows
        )
        target.execute(
            """
            CREATE UNIQUE INDEX idx_log_natural_key
            ON machine_logs(site_code, factory_code, log_event_id)
            """
        )
        return len(rows)
