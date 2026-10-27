"""Build and atomically publish the application-owned control catalog."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from capacity_twin_core.runtime.database_paths import get_control_run_pointer
from data_operations.generator.catalogs.contract_tables import (
    CATALOG_VERSION,
    build_resource_contracts,
)
from data_operations.generator.generators.assignment_matrix import ASSIGNMENT_MATRIX
from data_operations.generator.generators.reference_data import SITES
from data_operations.generator.generators.site_soft import SITE_OVERRIDES
from data_operations.generator.rules.npi import NPI_START_DATES

CONTROL_SCHEMA_VERSION = "control-1.0"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _assignment_rows() -> pd.DataFrame:
    rows = []
    for assignment in ASSIGNMENT_MATRIX:
        for test_type in assignment["test_types"]:
            rows.append(
                {
                    "site_code": assignment["site_code"],
                    "product_number": assignment["product_number"],
                    "product_family": assignment["product_family"],
                    "platform": assignment["platform"],
                    "product_level": assignment["product_level"],
                    "product_status": assignment["product_status"],
                    "test_type": test_type,
                    "catalog_version": CATALOG_VERSION,
                }
            )
    return pd.DataFrame(rows)


def _site_capabilities() -> pd.DataFrame:
    capabilities = (
        "PCBA",
        "RF",
        "MICROWAVE",
        "OPTICAL",
        "SYSTEM_INTEGRATION",
        "BOX_BUILD",
        "REPAIR",
        "NPI",
    )
    return pd.DataFrame(
        [
            {
                "site_code": site[0],
                "capability": capabilities[
                    (sum(site[0].encode("utf-8")) + offset) % len(capabilities)
                ],
                "catalog_version": CATALOG_VERSION,
            }
            for site in SITES
            for offset in range(3)
        ]
    )


def _noise_rules(config: dict[str, Any]) -> pd.DataFrame:
    dispositions = {
        "RAW_DUPLICATE_EXECUTION": "DEDUPLICATE",
        "RAW_MISSING_EXECUTION": "ACCEPT_MISSING_DAY",
        "RAW_NULL_MEASUREMENT": "QUARANTINE",
        "RAW_TEST_TIME_OUTLIER": "QUARANTINE",
    }
    return pd.DataFrame(
        [
            {
                "rule_id": rule_id,
                "expected_silver_disposition": dispositions.get(rule_id, "REVIEW"),
                "enabled": True,
            }
            for rule_id in config.get("noise", {}).get("allowed_rule_ids", [])
        ]
    )


def _calendar_overrides() -> pd.DataFrame:
    rows = []
    for site_code, values in sorted(SITE_OVERRIDES.items()):
        for control_name, control_value in sorted(values.items()):
            rows.append(
                {
                    "site_code": site_code,
                    "control_name": control_name,
                    "control_value": str(control_value),
                }
            )
    return pd.DataFrame(rows, columns=["site_code", "control_name", "control_value"])


def _npi_ramps() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "product_number": product_number,
                "qualification_start_date": start_date.isoformat(),
                "ramp_months": 12,
                "ramp_method": "LINEAR",
            }
            for product_number, start_date in sorted(NPI_START_DATES.items())
        ]
    )


def _comparison_windows(config: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {
            "window_id": "total",
            "display_name": "Total",
            "start_date": None,
            "end_date": None,
            "sort_order": 0,
        }
    ]
    for order, window_id in enumerate(("band_1", "band_2"), start=1):
        window = config["comparison_windows"][window_id]
        rows.append(
            {
                "window_id": window_id,
                "display_name": window["label"],
                "start_date": window["start_date"],
                "end_date": window["end_date"],
                "sort_order": order,
            }
        )
    return pd.DataFrame(rows)


def _source_registry(config: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_key": key,
                "database_file": filename,
                "ownership": "SOURCE_RAW",
                "source_system_type": "SIMULATED_SOURCE",
            }
            for key, filename in sorted(config["databases"]["raw"].items())
        ]
    )


def _write_table(
    connection: duckdb.DuckDBPyConnection,
    schema: str,
    table_name: str,
    frame: pd.DataFrame,
) -> None:
    connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    connection.register("_control_frame", frame)
    connection.execute(
        f'CREATE OR REPLACE TABLE "{schema}"."{table_name}" '
        "AS SELECT * FROM _control_frame"
    )
    connection.unregister("_control_frame")


def publish_control_catalog(config: dict[str, Any]) -> dict[str, Any]:
    """Compile, validate, and atomically promote one immutable control catalog."""
    runtime_home = Path(config["paths"]["runtime_home"]).resolve()
    run_id = f"control-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = runtime_home / "control" / "artifacts" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    database_name = config["databases"]["control"]["reference"]
    staged = run_dir / f"{database_name}.staging"
    final = run_dir / database_name

    resources = build_resource_contracts()
    tables: dict[tuple[str, str], pd.DataFrame] = {
        ("meta", "catalog_publication"): pd.DataFrame(
            [
                {
                    "control_run_id": run_id,
                    "schema_version": CONTROL_SCHEMA_VERSION,
                    "catalog_version": CATALOG_VERSION,
                    "published_at": _utc_now(),
                }
            ]
        ),
        ("meta", "source_registry"): _source_registry(config),
        ("crosswalk", "site_product_assignment"): _assignment_rows(),
        ("crosswalk", "site_capability"): _site_capabilities(),
        ("quality", "noise_rule"): _noise_rules(config),
        ("calendar", "calendar_override"): _calendar_overrides(),
        ("calendar", "npi_ramp"): _npi_ramps(),
        ("comparison", "comparison_window"): _comparison_windows(config),
        **{("resource", name): frame for name, frame in resources.items()},
    }

    with duckdb.connect(str(staged)) as connection:
        for (schema, table_name), frame in tables.items():
            _write_table(connection, schema, table_name, frame)
        duplicate_windows = connection.execute(
            """
            SELECT COUNT(*) - COUNT(DISTINCT window_id)
            FROM comparison.comparison_window
            """
        ).fetchone()[0]
        if duplicate_windows:
            raise ValueError("Comparison window IDs must be unique")
        invalid_windows = connection.execute(
            """
            SELECT COUNT(*)
            FROM comparison.comparison_window
            WHERE window_id <> 'total'
              AND (start_date IS NULL OR end_date IS NULL OR start_date > end_date)
            """
        ).fetchone()[0]
        if invalid_windows:
            raise ValueError("Comparison window dates are invalid")

    os.replace(staged, final)
    manifest = {
        "control_run_id": run_id,
        "schema_version": CONTROL_SCHEMA_VERSION,
        "catalog_version": CATALOG_VERSION,
        "published_at": _utc_now(),
        "database": str(final),
        "sha256": _checksum(final),
        "tables": {
            f"{schema}.{name}": len(frame)
            for (schema, name), frame in sorted(tables.items())
        },
    }
    manifest_path = run_dir / "manifest.json"
    _atomic_json(manifest_path, manifest)
    pointer = {
        "control_run_id": run_id,
        "catalog_version": CATALOG_VERSION,
        "database": str(final),
        "manifest": str(manifest_path),
        "sha256": manifest["sha256"],
        "promoted_at": manifest["published_at"],
    }
    _atomic_json(get_control_run_pointer(runtime_home), pointer)
    return pointer
