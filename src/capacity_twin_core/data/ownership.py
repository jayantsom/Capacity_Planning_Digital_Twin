"""Authoritative ownership boundary between source Raw and platform controls."""

from __future__ import annotations

from enum import StrEnum


class DataOwnership(StrEnum):
    """Identify who owns one persisted data object."""

    SOURCE_RAW = "SOURCE_RAW"
    APPLICATION_REFERENCE = "APPLICATION_REFERENCE"
    APPLICATION_MAPPING = "APPLICATION_MAPPING"


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
        "customer_order",
        "backlog_position",
        "constrained_production_plan",
        "shared_resource_allocation",
        "material_inventory_position",
        "inbound_receipt",
        "shipment",
        "safety_stock_policy",
        "service_target",
        "npi_program",
        "npi_stage_gate",
        "npi_milestone",
        "npi_qualification_evidence",
        "npi_pilot_lot",
        "npi_tooling_readiness",
        "npi_ramp_target",
        "npi_ramp_actual",
        "npi_risk",
        "npi_owner",
        "npi_status_history",
        "lot_route_movement_event",
        "production_schedule",
        "equipment_cost_reference",
    }
)

REFERENCE_TABLES = frozenset(
    {
        "meta.reference_publication",
        "canonical.site",
        "canonical.product",
        "canonical.test_type",
        "canonical.machine",
        "canonical.calendar",
        "canonical.unit",
        "canonical.controlled_code",
    }
)

MAPPING_TABLES = frozenset(
    {
        "meta.mapping_publication",
        "meta.source_registry",
        "crosswalk.site_product_assignment",
        "crosswalk.site_capability",
        "quality.noise_rule",
        "quality.mapping_exception",
        "calendar.calendar_override",
        "calendar.npi_ramp",
        "resource.resource_master",
        "resource.resource_pool",
        "resource.product_resource_qualification",
        "resource.tester_fixture_compatibility",
        "resource.multi_dut_configuration",
    }
)

APPLICATION_CONTROL_TABLES = REFERENCE_TABLES | MAPPING_TABLES

RAW_DATABASE_TABLES = {
    "demand": frozenset(
        {
            "demand_requirement",
            "customer_order",
            "backlog_position",
            "constrained_production_plan",
            "shared_resource_allocation",
        }
    ),
    "product": frozenset(
        {
            "manufacturer_master",
            "product_master",
            "product_bom",
            "product_route",
            "route_step",
            "site_product_source",
        }
    ),
    "site": frozenset({"site_master", "site_soft"}),
    "machine": frozenset(
        {
            "equipment_master",
            "site_equipment_inventory",
            "machine_logs",
            "equipment_cost_reference",
        }
    ),
    "test": frozenset(
        {"test_type_master", "target_test_time", "machine_test_param"}
    ),
    "yield": frozenset({"target_yield"}),
    "execution": frozenset(
        {"machine_execution", "lot_route_movement_event", "production_schedule"}
    ),
    "inventory": frozenset(
        {
            "material_inventory_position",
            "inbound_receipt",
            "shipment",
            "safety_stock_policy",
            "service_target",
        }
    ),
    "npi": frozenset(
        {
            "npi_program",
            "npi_stage_gate",
            "npi_milestone",
            "npi_qualification_evidence",
            "npi_pilot_lot",
            "npi_tooling_readiness",
            "npi_ramp_target",
            "npi_ramp_actual",
            "npi_risk",
            "npi_owner",
            "npi_status_history",
        }
    ),
}

_OWNERSHIP = {
    **{table: DataOwnership.SOURCE_RAW for table in SOURCE_RAW_TABLES},
    **{
        table: DataOwnership.APPLICATION_REFERENCE for table in REFERENCE_TABLES
    },
    **{
        table: DataOwnership.APPLICATION_MAPPING for table in MAPPING_TABLES
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
    unowned = sorted(table_names - SOURCE_RAW_TABLES)
    misplaced = sorted(table_names & {name.rsplit(".", 1)[-1] for name in APPLICATION_CONTROL_TABLES})
    if misplaced:
        raise ValueError(f"Application controls cannot be emitted into Raw: {misplaced}")
    if unowned:
        raise ValueError(f"Raw tables lack ownership metadata: {unowned}")
