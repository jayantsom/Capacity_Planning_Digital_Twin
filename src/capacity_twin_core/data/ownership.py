"""Authoritative ownership boundary between source Raw and platform controls."""

from __future__ import annotations

from enum import StrEnum


class DataOwnership(StrEnum):
    """Identify who owns one persisted data object."""

    SOURCE_RAW = "SOURCE_RAW"
    APPLICATION_CONTROL = "APPLICATION_CONTROL"


SOURCE_RAW_TABLES = frozenset(
    {
        "site_master",
        "test_type_master",
        "equipment_master",
        "manufacturer_master",
        "product_master",
        "product_bom",
        "product_route",
        "route_step",
        "site_product_source",
        "demand_requirement",
        "target_test_time",
        "target_yield",
        "site_equipment_inventory",
        "site_soft",
        "machine_execution",
        "machine_test_param",
        "machine_logs",
    }
)

APPLICATION_CONTROL_TABLES = frozenset(
    {
        "catalog_publication",
        "source_registry",
        "site_product_assignment",
        "resource_master",
        "resource_pool",
        "product_resource_qualification",
        "tester_fixture_compatibility",
        "multi_dut_configuration",
        "site_capability",
        "noise_rule",
        "calendar_override",
        "npi_ramp",
        "comparison_window",
    }
)

_OWNERSHIP = {
    **{table: DataOwnership.SOURCE_RAW for table in SOURCE_RAW_TABLES},
    **{
        table: DataOwnership.APPLICATION_CONTROL
        for table in APPLICATION_CONTROL_TABLES
    },
}


def ownership_for(table_name: str) -> DataOwnership:
    """Return declared ownership and reject unclassified persisted tables."""
    try:
        return _OWNERSHIP[table_name]
    except KeyError as error:
        raise ValueError(f"Unclassified persisted table: {table_name}") from error


def assert_raw_tables(table_names: set[str]) -> None:
    """Fail when application controls are accidentally emitted into Raw."""
    misplaced = sorted(table_names & APPLICATION_CONTROL_TABLES)
    if misplaced:
        raise ValueError(f"Application controls cannot be emitted into Raw: {misplaced}")
