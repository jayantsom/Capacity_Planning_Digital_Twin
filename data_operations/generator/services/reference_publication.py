"""Build the application-owned canonical reference database."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

from data_operations.generator.catalogs.contract_tables import CATALOG_VERSION
from data_operations.generator.generators.product_master import generate_product_master
from data_operations.generator.generators.reference_data import (
    generate_equipment_master,
    generate_site_master,
    generate_test_type_master,
)

REFERENCE_SCHEMA_VERSION = "reference-1.0"


def _write_table(
    connection: duckdb.DuckDBPyConnection,
    schema: str,
    name: str,
    frame: pd.DataFrame,
) -> None:
    connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    connection.register("_reference_frame", frame)
    connection.execute(
        f'CREATE TABLE "{schema}"."{name}" AS SELECT * FROM _reference_frame'
    )
    connection.unregister("_reference_frame")


def build_reference_database(
    path: Path,
    *,
    source_run_id: str,
    published_at: str,
) -> dict[str, int]:
    """Write canonical entities and controlled values to one immutable file."""
    staged = path.with_suffix(f"{path.suffix}.staging")
    sites = generate_site_master()
    products = generate_product_master()
    tests = generate_test_type_master()
    machines = generate_equipment_master()
    tables = {
        ("meta", "reference_publication"): pd.DataFrame(
            [
                {
                    "source_run_id": source_run_id,
                    "schema_version": REFERENCE_SCHEMA_VERSION,
                    "catalog_version": CATALOG_VERSION,
                    "published_at": published_at,
                }
            ]
        ),
        ("canonical", "site"): sites,
        ("canonical", "product"): products,
        ("canonical", "test_type"): tests,
        ("canonical", "machine"): machines,
        ("canonical", "calendar"): sites[["site_code"]]
        .rename(columns={"site_code": "canonical_site_id"})
        .assign(calendar_id=lambda frame: "CAL-" + frame["canonical_site_id"]),
        ("canonical", "unit"): pd.DataFrame(
            [
                {"unit_code": "EA", "unit_name": "Each", "dimension": "quantity"},
                {"unit_code": "SEC", "unit_name": "Second", "dimension": "time"},
                {"unit_code": "HR", "unit_name": "Hour", "dimension": "time"},
                {"unit_code": "MIN", "unit_name": "Minute", "dimension": "time"},
                {"unit_code": "DAY", "unit_name": "Day", "dimension": "time"},
                {"unit_code": "PCT", "unit_name": "Percent", "dimension": "ratio"},
                {"unit_code": "USD", "unit_name": "US Dollar", "dimension": "currency"},
                {"unit_code": "SCORE", "unit_name": "Score", "dimension": "index"},
                {"unit_code": "COUNT", "unit_name": "Count", "dimension": "count"},
                {
                    "unit_code": "EA_PER_HR",
                    "unit_name": "Each per hour",
                    "dimension": "rate",
                },
            ]
        ),
        ("canonical", "controlled_code"): pd.DataFrame(
            [
                {"code_set": "data_type", "code": "ACTUAL"},
                {"code_set": "data_type", "code": "FORECAST"},
                {"code_set": "capacity_mode", "code": "NORMAL"},
                {"code_set": "capacity_mode", "code": "MAXIMUM"},
            ]
        ),
    }
    with duckdb.connect(str(staged)) as connection:
        for (schema, name), frame in tables.items():
            _write_table(connection, schema, name, frame)
    os.replace(staged, path)
    return {
        f"{schema}.{name}": len(frame)
        for (schema, name), frame in sorted(tables.items())
    }
