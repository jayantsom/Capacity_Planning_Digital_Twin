"""Build source-to-canonical crosswalks and governed assignment rules."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from data_operations.generator.catalogs.contract_tables import (
    CATALOG_VERSION,
    build_resource_contracts,
)
from data_operations.generator.generators.assignment_matrix import ASSIGNMENT_MATRIX
from data_operations.generator.generators.product_master import PRODUCTS
from data_operations.generator.generators.reference_data import SITES, TEST_TYPES
from data_operations.generator.generators.site_soft import SITE_OVERRIDES
from data_operations.generator.rules.npi import NPI_START_DATES

MAPPING_SCHEMA_VERSION = "mapping-1.0"
EFFECTIVE_START = "2023-01-01"
EFFECTIVE_END = "9999-12-31"


def _effective(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "effective_start_date" not in result:
        result["effective_start_date"] = EFFECTIVE_START
    if "effective_end_date" not in result:
        result["effective_end_date"] = EFFECTIVE_END
    return result


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
    return _effective(pd.DataFrame(rows))


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
    rows = [
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
    return _effective(pd.DataFrame(rows))


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
    rows = [
        {
            "site_code": site_code,
            "control_name": control_name,
            "control_value": str(control_value),
        }
        for site_code, values in sorted(SITE_OVERRIDES.items())
        for control_name, control_value in sorted(values.items())
    ]
    return _effective(pd.DataFrame(rows))


def _npi_ramps() -> pd.DataFrame:
    return _effective(
        pd.DataFrame(
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
    )


def _source_registry(config: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_system_id": key,
                "database_file": filename,
                "ownership": "SOURCE_RAW",
                "source_system_type": "SIMULATED_SOURCE",
            }
            for key, filename in sorted(config["databases"]["raw"].items())
        ]
    )


def _validate_mappings(tables: dict[tuple[str, str], pd.DataFrame]) -> None:
    assignments = tables[("crosswalk", "site_product_assignment")]
    key = ["site_code", "product_number", "test_type", "effective_start_date"]
    if assignments.duplicated(key).any():
        raise ValueError("Site-product-test crosswalks are not unique")
    interval_key = ["site_code", "product_number", "test_type"]
    for _, group in assignments.sort_values("effective_start_date").groupby(interval_key):
        previous_end: str | None = None
        for row in group.itertuples(index=False):
            if previous_end is not None and row.effective_start_date <= previous_end:
                raise ValueError("Site-product-test crosswalk intervals overlap")
            previous_end = row.effective_end_date
    if not set(assignments["site_code"]) <= {row[0] for row in SITES}:
        raise ValueError("Mapping references an unknown canonical site")
    if not set(assignments["product_number"]) <= {row[0] for row in PRODUCTS}:
        raise ValueError("Mapping references an unknown canonical product")
    if not set(assignments["test_type"]) <= {row[0] for row in TEST_TYPES}:
        raise ValueError("Mapping references an unknown canonical test type")
    expected = {
        (row["site_code"], row["product_number"], test_type)
        for row in ASSIGNMENT_MATRIX
        for test_type in row["test_types"]
    }
    actual = set(
        assignments[["site_code", "product_number", "test_type"]]
        .itertuples(index=False, name=None)
    )
    if expected != actual:
        raise ValueError("Mapping coverage is incomplete")
    qualifications = tables[("resource", "product_resource_qualification")]
    qualification_key = [
        "site_code",
        "product_number",
        "test_type",
        "resource_id",
        "effective_start_date",
    ]
    if qualifications.duplicated(qualification_key).any():
        raise ValueError("Product-resource qualifications are not unique")


def _write_table(
    connection: duckdb.DuckDBPyConnection,
    schema: str,
    name: str,
    frame: pd.DataFrame,
) -> None:
    connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    connection.register("_mapping_frame", frame)
    connection.execute(
        f'CREATE TABLE "{schema}"."{name}" AS SELECT * FROM _mapping_frame'
    )
    connection.unregister("_mapping_frame")


def build_mapping_database(
    path: Path,
    config: dict[str, Any],
    *,
    source_run_id: str,
    published_at: str,
) -> dict[str, int]:
    """Write validated crosswalks, assignments, compatibility, and overrides."""
    resources = {
        ("resource", name): _effective(frame)
        for name, frame in build_resource_contracts().items()
    }
    tables: dict[tuple[str, str], pd.DataFrame] = {
        ("meta", "mapping_publication"): pd.DataFrame(
            [
                {
                    "source_run_id": source_run_id,
                    "schema_version": MAPPING_SCHEMA_VERSION,
                    "catalog_version": CATALOG_VERSION,
                    "published_at": published_at,
                }
            ]
        ),
        ("meta", "source_registry"): _source_registry(config),
        ("crosswalk", "site_product_assignment"): _assignment_rows(),
        ("crosswalk", "site_capability"): _site_capabilities(),
        ("quality", "noise_rule"): _noise_rules(config),
        ("quality", "mapping_exception"): pd.DataFrame(
            columns=["exception_id", "mapping_name", "source_value", "reason"]
        ),
        ("calendar", "calendar_override"): _calendar_overrides(),
        ("calendar", "npi_ramp"): _npi_ramps(),
        **resources,
    }
    _validate_mappings(tables)
    staged = path.with_suffix(f"{path.suffix}.staging")
    with duckdb.connect(str(staged)) as connection:
        for (schema, name), frame in tables.items():
            _write_table(connection, schema, name, frame)
    os.replace(staged, path)
    return {
        f"{schema}.{name}": len(frame)
        for (schema, name), frame in sorted(tables.items())
    }
