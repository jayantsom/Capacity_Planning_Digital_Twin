"""Load and validate tracked source data contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONTRACT_ROOT = Path(__file__).resolve().parent


def load_contract(name: str) -> dict[str, Any]:
    """Load one repository-owned YAML contract by stable name."""
    if name not in {"source_to_serving", "raw_migration"}:
        raise ValueError(f"Unknown data contract: {name}")
    with (CONTRACT_ROOT / f"{name}.yaml").open(encoding="utf-8") as file:
        value = yaml.safe_load(file)
    if not isinstance(value, dict):
        raise TypeError(f"Invalid data contract: {name}")
    return value


def validate_contracts() -> None:
    """Fail when source contracts or the one-time migration matrix drift."""
    source = load_contract("source_to_serving")
    migration = load_contract("raw_migration")
    required = set(source["required_fields"])
    for table, contract in {
        **source["tables"],
        **source.get("metrics", {}),
        **source.get("datasets", {}),
    }.items():
        missing = required - set(contract)
        if missing:
            raise ValueError(f"{table} contract is missing {sorted(missing)}")

    assignments = [
        (database, table, details["target_database"])
        for database, tables in migration["current_to_target"].items()
        for table, details in tables.items()
    ]
    if len(assignments) != migration["current_table_count"]:
        raise ValueError("Migration matrix does not contain all current tables")
    table_names = [table for _database, table, _target in assignments]
    if len(table_names) != len(set(table_names)):
        raise ValueError("A current Raw table is assigned more than once")
    targets = set(migration["target_databases"])
    if {target for _database, _table, target in assignments} - targets:
        raise ValueError("Migration matrix references an unknown target database")
