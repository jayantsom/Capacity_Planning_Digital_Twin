"""Machine-readable source contract completeness tests."""

from capacity_twin_core.data.contracts import load_contract, validate_contracts
from capacity_twin_core.data.ownership import SOURCE_RAW_TABLES


def test_source_contracts_cover_every_current_raw_table() -> None:
    validate_contracts()
    contract = load_contract("source_to_serving")
    assert set(contract["tables"]) == SOURCE_RAW_TABLES


def test_migration_assigns_all_tables_once_to_nine_databases() -> None:
    migration = load_contract("raw_migration")
    assignments = [
        details["target_database"]
        for tables in migration["current_to_target"].values()
        for details in tables.values()
    ]
    assert len(assignments) == 17
    assert set(assignments) <= set(migration["target_databases"])
    assert len(migration["target_databases"]) == 9


def test_phase6_serving_datasets_have_machine_readable_contracts() -> None:
    datasets = load_contract("source_to_serving")["datasets"]
    assert set(datasets) == {
        "srv_sop_balance",
        "srv_npi_readiness",
        "srv_npi_ramp",
        "srv_operations_wip",
        "srv_operations_queue",
        "srv_operations_cycle_time",
        "srv_operations_throughput",
        "srv_operations_rework",
        "srv_operations_route_adherence",
        "srv_operations_schedule_attainment",
        "srv_operations_bottleneck_movement",
        "srv_scenario_inputs",
        "srv_equipment_cost_reference",
    }
