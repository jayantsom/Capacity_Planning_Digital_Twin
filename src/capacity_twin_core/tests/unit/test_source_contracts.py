"""Machine-readable source contract completeness tests."""

from capacity_twin_core.data.contracts import load_contract, validate_contracts
from capacity_twin_core.data.ownership import SOURCE_RAW_TABLES


def test_source_contracts_cover_every_current_raw_table() -> None:
    validate_contracts()
    contract = load_contract("source_to_serving")
    assert set(contract["tables"]) == SOURCE_RAW_TABLES


def test_migration_assigns_all_tables_once_to_seven_databases() -> None:
    migration = load_contract("raw_migration")
    assignments = [
        details["target_database"]
        for tables in migration["current_to_target"].values()
        for details in tables.values()
    ]
    assert len(assignments) == 17
    assert set(assignments) <= set(migration["target_databases"])
    assert len(migration["target_databases"]) == 7
