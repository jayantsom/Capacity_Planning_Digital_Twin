"""Read the immutable control catalog used by one Raw generation run."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


def _catalog_path(config: dict[str, Any]) -> Path:
    publication = config.get("control_publication", {})
    database = publication.get("database")
    if not database:
        raise ValueError("Raw generation requires a published control catalog")
    path = Path(database)
    if not path.is_file():
        raise FileNotFoundError(f"Control catalog not found: {path}")
    return path


def read_control_table(
    config: dict[str, Any],
    schema: str,
    table_name: str,
) -> pd.DataFrame:
    """Read one application-owned control table as a DataFrame."""
    with duckdb.connect(str(_catalog_path(config)), read_only=True) as connection:
        return connection.execute(
            f'SELECT * FROM "{schema}"."{table_name}"'
        ).df()


def load_assignments(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Rebuild generator assignment records from the published crosswalk."""
    frame = read_control_table(config, "crosswalk", "site_product_assignment")
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    test_types: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in frame.to_dict("records"):
        key = (row["site_code"], row["product_number"])
        grouped.setdefault(
            key,
            {
                "site_code": row["site_code"],
                "product_number": row["product_number"],
                "product_family": row["product_family"],
                "platform": row["platform"],
                "product_level": row["product_level"],
            },
        )
        test_types[key].append(row["test_type"])
    return [
        {**record, "test_types": sorted(set(test_types[key]))}
        for key, record in sorted(grouped.items())
    ]


def load_resource_contracts(config: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Read all qualified resource-control tables from the publication."""
    table_names = (
        "resource_master",
        "resource_pool",
        "product_resource_qualification",
        "tester_fixture_compatibility",
        "multi_dut_configuration",
    )
    return {
        table_name: read_control_table(config, "resource", table_name)
        for table_name in table_names
    }
