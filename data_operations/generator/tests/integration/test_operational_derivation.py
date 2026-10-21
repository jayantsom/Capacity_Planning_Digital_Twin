"""Tiny integration check for execution-derived parameter and log facts."""

import sqlite3
from pathlib import Path

from data_operations.generator.services.operational_derivation import (
    derive_logs,
    derive_test_parameters,
)


def _write_execution(path: Path) -> None:
    """Create one excursion without invoking the full-history generator."""
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE machine_execution (
                record_id TEXT, event_id TEXT, factory_code TEXT, site_code TEXT,
                product_number TEXT, test_category_id TEXT, test_type TEXT,
                execution_date TEXT, month_key INTEGER, passed_qty INTEGER,
                failed_qty INTEGER, total_qty INTEGER, yield_avg REAL,
                test_duration_avg_sec REAL, equipment_downtime_avg_sec REAL,
                noise_rule_id TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO machine_execution VALUES
            ('record-1', 'event-1', 'FACTORY', 'SITE', 'PRODUCT', '100', 'FCT',
             '2026-10-31', 202610, 70, 30, 100, 0.70, 300, 0, NULL)
            """
        )


def test_parameters_and_logs_reference_canonical_execution(tmp_path: Path) -> None:
    execution = tmp_path / "execution.db"
    parameters = tmp_path / "parameters.db"
    logs = tmp_path / "logs.db"
    _write_execution(execution)

    assert derive_test_parameters(execution, parameters) == 1
    assert derive_logs(execution, logs) == 1

    with sqlite3.connect(parameters) as connection:
        assert connection.execute(
            "SELECT first_pass_qty, first_fail_qty, total_qty FROM machine_test_param"
        ).fetchone() == (70, 30, 100)
    with sqlite3.connect(logs) as connection:
        assert connection.execute(
            "SELECT execution_record_id, event_id, site_code, factory_code FROM machine_logs"
        ).fetchone() == ("record-1", "event-1", "SITE", "FACTORY")
