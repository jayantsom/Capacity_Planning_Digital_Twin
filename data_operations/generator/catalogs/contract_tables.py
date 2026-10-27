"""Build the versioned telecom routing, sourcing, and resource catalog."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from data_operations.generator.generators.assignment_matrix import ASSIGNMENT_MATRIX
from data_operations.generator.generators.product_master import PRODUCTS
from data_operations.generator.generators.reference_data import FIXTURES, SYSTEMS
from data_operations.generator.rules.contracts import RESOURCE_SCENARIOS
from data_operations.generator.rules.determinism import stable_id

CATALOG_VERSION = "telecom-1.0"
SYNTHETIC_DISCLAIMER = (
    "Synthetic educational data. Names of real manufacturers are references only; "
    "sites, capabilities, products, volumes, routes, and performance imply no affiliation."
)


def _product_rows() -> dict[str, tuple]:
    return {row[0]: row for row in PRODUCTS}


def build_product_bom() -> pd.DataFrame:
    """Return effective-dated parent-to-child quantities."""
    rows: list[dict] = []
    for product in PRODUCTS:
        parent = product[0]
        for child, quantity in ((product[7], product[8]), (product[9], product[10]), (product[11], product[12])):
            if child:
                rows.append(
                    {
                        "bom_id": stable_id("bom", parent, child),
                        "catalog_version": CATALOG_VERSION,
                        "parent_product_number": parent,
                        "child_product_number": child,
                        "quantity_per_parent": int(quantity),
                        "effective_start_date": "2023-01-01",
                        "effective_end_date": "2027-12-31",
                        "provenance": "SYNTHETIC_ASSUMPTION",
                    }
                )
    return pd.DataFrame(rows)


def build_routes(
    assignments: list[dict] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return one route and ordered, capacity-aware steps per product."""
    assignments_by_product: dict[str, dict] = {}
    for assignment in assignments or ASSIGNMENT_MATRIX:
        assignments_by_product.setdefault(assignment["product_number"], assignment)

    route_rows: list[dict] = []
    step_rows: list[dict] = []
    paired_tests = {fixture[3] for fixture in FIXTURES if fixture[6] is not None}
    standalone_tests = {fixture[3] for fixture in FIXTURES if fixture[6] is None}
    for product_number, assignment in sorted(assignments_by_product.items()):
        route_id = stable_id("route", product_number, CATALOG_VERSION)
        route_rows.append(
            {
                "route_id": route_id,
                "catalog_version": CATALOG_VERSION,
                "product_number": product_number,
                "product_level": assignment["product_level"],
                "effective_start_date": "2023-01-01",
                "effective_end_date": "2027-12-31",
                "is_active": 1,
            }
        )
        for sequence, test_type in enumerate(assignment["test_types"], start=1):
            # The deterministic rotation guarantees coverage of every approved behavior.
            scenario = RESOURCE_SCENARIOS[
                (sum(product_number.encode("utf-8")) + sequence - 1) % len(RESOURCE_SCENARIOS)
            ]
            if scenario == "PAIRED_FIXTURE" and test_type not in paired_tests:
                scenario = "SERIAL_STEP"
            if scenario == "PAIRED_FIXTURE" and sum(product_number.encode()) % 4 != 0:
                # Passive pairs are intentionally sparse under the 300-row inventory cap.
                scenario = "SERIAL_STEP"
            if scenario == "STANDALONE" and test_type not in standalone_tests:
                scenario = "SERIAL_STEP"
            step_rows.append(
                {
                    "route_step_id": stable_id("step", route_id, sequence),
                    "route_id": route_id,
                    "step_sequence": sequence,
                    "test_type": test_type,
                    "capacity_behavior": scenario,
                    "full_demand_required": 1,
                    "provenance": "SYNTHETIC_ROUTE_RULE",
                }
            )
    return pd.DataFrame(route_rows), pd.DataFrame(step_rows)


def build_site_product_sources(
    assignments: list[dict] | None = None,
) -> pd.DataFrame:
    """Return sparse source allocations that conserve each product's demand."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for assignment in assignments or ASSIGNMENT_MATRIX:
        grouped[assignment["product_number"]].append(assignment)

    product_rows = _product_rows()
    rows: list[dict] = []
    for product_number, product_assignments in sorted(grouped.items()):
        count = len(product_assignments)
        policy = "MAKE"
        if product_rows[product_number][7] is None and product_number.endswith(("041", "043")):
            policy = "BUY_TESTED"
        elif product_rows[product_number][7] is None and product_number.endswith(("042", "044")):
            policy = "BUY_REQUIRES_INCOMING_TEST"
        allocations = [round(1 / count, 6)] * count
        allocations[-1] = round(1 - sum(allocations[:-1]), 6)
        for assignment, allocation in zip(
            product_assignments, allocations, strict=True
        ):
            rows.append(
                {
                    "source_id": stable_id("source", product_number, assignment["site_code"]),
                    "catalog_version": CATALOG_VERSION,
                    "product_number": product_number,
                    "site_code": assignment["site_code"],
                    "source_policy": policy,
                    "allocation_ratio": allocation,
                    "effective_start_date": "2023-01-01",
                    "effective_end_date": "2027-12-31",
                    "transfer_to_assembly_site": int(assignment["product_level"] == "CHILD"),
                }
            )
    return pd.DataFrame(rows)


def build_resource_contracts(
    assignments: list[dict] | None = None,
) -> dict[str, pd.DataFrame]:
    """Return resources, pools, qualifications, compatibility, and multi-DUT limits."""
    resource_rows: list[dict] = []
    pool_rows: list[dict] = []
    systems_by_test: dict[str, list[str]] = defaultdict(list)
    for system in SYSTEMS:
        equipment_id, _name, family, test_type, manufacturer, model, _slots = system
        systems_by_test[test_type].append(equipment_id)
        resource_rows.append(
            {
                "resource_id": equipment_id,
                "resource_kind": "TEST_SYSTEM",
                "resource_family": family,
                "test_type": test_type,
                "manufacturer": manufacturer,
                "model_number": model,
                "is_passive": 0,
                "provenance": "PUBLIC_CATEGORY_SYNTHETIC_CONFIGURATION",
            }
        )
        pool_rows.append(
            {
                "pool_id": f"POOL-{test_type}",
                "resource_id": equipment_id,
                "test_type": test_type,
                "pool_behavior": "ALTERNATIVE_POOL",
            }
        )

    compatibility_rows: list[dict] = []
    for fixture in FIXTURES:
        equipment_id, _name, family, test_type, manufacturer, model, parent, _shared = fixture
        is_standalone = parent is None
        resource_rows.append(
            {
                "resource_id": equipment_id,
                "resource_kind": "ACTIVE_FIXTURE" if is_standalone else "PASSIVE_FIXTURE",
                "resource_family": family,
                "test_type": test_type,
                "manufacturer": manufacturer,
                "model_number": model,
                "is_passive": 0 if is_standalone else 1,
                "provenance": "SYNTHETIC_CUSTOM_FIXTURE",
            }
        )
        if not is_standalone:
            compatibility_rows.append(
                {
                    "compatibility_id": stable_id("compat", parent, equipment_id),
                    "tester_resource_id": parent,
                    "fixture_resource_id": equipment_id,
                    "handler_resource_id": None,
                    "fixture_slots_required": 1,
                    "is_active": 1,
                }
            )

    qualification_rows: list[dict] = []
    route_df, step_df = build_routes(assignments)
    product_by_route = dict(zip(route_df["route_id"], route_df["product_number"], strict=True))
    behavior_by_product_test = {
        (product_by_route[row["route_id"]], row["test_type"]): row["capacity_behavior"]
        for row in step_df.to_dict("records")
    }
    active_by_test = {
        fixture[3]: fixture[0] for fixture in FIXTURES if fixture[6] is None
    }
    paired_systems_by_test: dict[str, list[str]] = defaultdict(list)
    for fixture in FIXTURES:
        if fixture[6] is not None:
            paired_systems_by_test[fixture[3]].append(fixture[6])
    for assignment in assignments or ASSIGNMENT_MATRIX:
        for test_type in assignment["test_types"]:
            behavior = behavior_by_product_test[(assignment["product_number"], test_type)]
            if behavior == "STANDALONE":
                selected = active_by_test[test_type]
                systems = []
            elif behavior == "PAIRED_FIXTURE":
                systems = sorted(set(paired_systems_by_test[test_type]))
            else:
                systems = systems_by_test[test_type]
            if systems:
                selected = systems[
                    sum(f"{assignment['site_code']}|{test_type}".encode())
                    % len(systems)
                ]
            qualification_rows.append(
                {
                    "qualification_id": stable_id(
                        "qualification", assignment["site_code"], assignment["product_number"], test_type
                    ),
                    "site_code": assignment["site_code"],
                    "product_number": assignment["product_number"],
                    "test_type": test_type,
                    "resource_id": selected,
                    "pool_id": f"POOL-{test_type}",
                    "capacity_behavior": behavior,
                    "is_primary": 1,
                    "effective_start_date": "2023-01-01",
                    "effective_end_date": "2027-12-31",
                }
            )

    multi_rows: list[dict] = []
    for index, system in enumerate(SYSTEMS):
        system_id = system[0]
        tester_channels = (2, 4, 8, 16)[index % 4]
        enabled_ports = max(1, tester_channels - (1 if index % 3 == 0 else 0))
        fixture_slots = max(1, min(system[6] or 1, enabled_ports))
        cavities = min(enabled_ports, fixture_slots * 2)
        handler_sockets = min(enabled_ports, cavities)
        multi_rows.append(
            {
                "configuration_id": stable_id("multi-dut", system_id),
                "resource_id": system_id,
                "tester_channels": tester_channels,
                "enabled_licensed_ports": enabled_ports,
                "tester_fixture_slots": fixture_slots,
                "fixture_cavities": cavities,
                "handler_sockets": handler_sockets,
                "fixtures_required_per_system": 1,
                "execution_mode": "ASYNCHRONOUS" if index % 2 else "SYNCHRONOUS",
                "batch_cycle_time_sec": 180 + index * 30,
                "changeover_time_sec": 300 + index * 45,
                "parallel_efficiency": round(0.78 + index * 0.02, 2),
                "effective_parallel_duts": min(
                    tester_channels, enabled_ports, fixture_slots, cavities, handler_sockets
                ),
            }
        )

    return {
        "resource_master": pd.DataFrame(resource_rows),
        "resource_pool": pd.DataFrame(pool_rows),
        "product_resource_qualification": pd.DataFrame(qualification_rows),
        "tester_fixture_compatibility": pd.DataFrame(compatibility_rows),
        "multi_dut_configuration": pd.DataFrame(multi_rows),
    }
