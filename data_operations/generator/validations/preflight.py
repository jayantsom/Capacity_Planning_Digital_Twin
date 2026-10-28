"""No-write checks for catalog connectivity, scale, and rule integrity."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from capacity_twin_core.data.contracts import validate_contracts
from data_operations.generator.catalogs.contract_tables import (
    build_product_bom,
    build_resource_contracts,
    build_routes,
    build_site_product_sources,
)
from data_operations.generator.generators.assignment_matrix import ASSIGNMENT_MATRIX
from data_operations.generator.generators.product_master import PRODUCTS
from data_operations.generator.generators.reference_data import FIXTURES, SITES, SYSTEMS, TEST_TYPES
from data_operations.generator.rules.contracts import (
    RESOURCE_SCENARIOS,
    DateContract,
    VolumeContract,
)


def _bom_has_cycle() -> bool:
    graph: dict[str, list[str]] = defaultdict(list)
    for row in build_product_bom().to_dict("records"):
        graph[row["parent_product_number"]].append(row["child_product_number"])

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(product: str) -> bool:
        if product in visiting:
            return True
        if product in visited:
            return False
        visiting.add(product)
        if any(visit(child) for child in graph[product]):
            return True
        visiting.remove(product)
        visited.add(product)
        return False

    return any(visit(product) for product in list(graph))


def estimate_rows(config: dict[str, Any]) -> dict[str, int]:
    """Calculate exact profile projections before any database is written."""
    dates = DateContract.from_config(config)
    volume = VolumeContract.from_config(config)
    route_steps = sum(len(assignment["test_types"]) for assignment in ASSIGNMENT_MATRIX)
    calendar_days = (dates.actual_end - dates.actual_start) // timedelta(days=1) + 1
    sampled_days = (calendar_days + volume.execution_day_stride - 1) // volume.execution_day_stride
    execution = route_steps * sampled_days
    # Weekend and intentional missing-day rules only reduce these conservative projections.
    return {
        "active_site_product_route_steps": route_steps,
        "machine_execution": execution,
        "machine_test_param": execution,
        "machine_logs": min(execution, int(execution * 0.12)),
        "estimated_raw_bytes": execution * 900,
        "estimated_temporary_bytes": execution * 1_800,
        "approximate_spark_partitions": max(1, (execution + 199_999) // 200_000),
    }


def validate_preflight(config: dict[str, Any]) -> dict[str, Any]:
    """Raise one readable error if the immutable catalog cannot be generated."""
    validate_contracts()
    caps = config["local_16gb"]
    errors: list[str] = []
    expected_raw_files = {
        "raw_demand.db",
        "raw_product.db",
        "raw_site.db",
        "raw_machine.db",
        "raw_test.db",
        "raw_yield.db",
        "raw_execution.db",
    }
    configured_raw_files = set(config["databases"]["raw"].values())
    if configured_raw_files != expected_raw_files:
        errors.append("Raw database map must contain the seven governed source files")
    product_numbers = {product[0] for product in PRODUCTS}
    test_types = {test[0] for test in TEST_TYPES}
    route_df, step_df = build_routes()
    product_by_route = dict(zip(route_df["route_id"], route_df["product_number"], strict=True))
    behavior_by_product_test = {
        (product_by_route[row["route_id"]], row["test_type"]): row["capacity_behavior"]
        for row in step_df.to_dict("records")
    }
    sources = build_site_product_sources()
    resources = build_resource_contracts()

    count_checks = {
        "active sites": (len(SITES), caps["max_active_sites"]),
        "active products": (len(PRODUCTS), caps["max_active_products"]),
        "active test types": (len(TEST_TYPES), caps["max_active_test_types"]),
        "tester/system definitions": (len(SYSTEMS), caps["max_systems"]),
        "fixture/handler definitions": (len(FIXTURES), caps["max_fixtures_handlers"]),
        "site-product assignments": (len(ASSIGNMENT_MATRIX), caps["max_site_product_assignments"]),
    }
    qualification_table = resources["product_resource_qualification"].copy()
    qualification_table["capacity_behavior"] = [
        behavior_by_product_test[(row.product_number, row.test_type)]
        for row in qualification_table.itertuples()
    ]
    qualification_inventory = qualification_table[["site_code", "resource_id"]].drop_duplicates()
    compatibility_inventory = resources["tester_fixture_compatibility"][
        ["tester_resource_id", "fixture_resource_id"]
    ]
    paired_inventory = (
        qualification_table[qualification_table["capacity_behavior"] == "PAIRED_FIXTURE"][
            ["site_code", "resource_id"]
        ]
        .drop_duplicates()
        .merge(
            compatibility_inventory,
            left_on="resource_id",
            right_on="tester_resource_id",
            how="inner",
        )[["site_code", "fixture_resource_id"]]
        .drop_duplicates()
    )
    inventory_relationships = len(qualification_inventory) + len(paired_inventory)
    count_checks["site-resource inventory relationships"] = (
        inventory_relationships,
        caps["max_site_resource_relationships"],
    )
    for label, (actual, maximum) in count_checks.items():
        if actual > maximum:
            errors.append(f"{label} {actual} exceeds cap {maximum}")

    if _bom_has_cycle():
        errors.append("product BOM contains a cycle")
    bom_children = set(build_product_bom()["child_product_number"])
    if not bom_children <= product_numbers:
        errors.append(f"BOM has missing children: {sorted(bom_children - product_numbers)}")

    if route_df["product_number"].nunique() != len(PRODUCTS):
        errors.append("every product must have exactly one active route")
    route_sizes = step_df.groupby("route_id")["step_sequence"].agg(["count", "nunique", "max"])
    if (route_sizes["count"] != route_sizes["nunique"]).any():
        errors.append("route step sequences must be unique")
    if (route_sizes["max"] > caps["max_route_steps"]).any():
        errors.append("a product route exceeds the configured route-step cap")
    if not set(step_df["test_type"]) <= test_types:
        errors.append("a route references an unknown test type")
    missing_behaviors = set(RESOURCE_SCENARIOS) - set(step_df["capacity_behavior"])
    if missing_behaviors:
        errors.append(f"resource behavior coverage is incomplete: {sorted(missing_behaviors)}")

    allocation = sources.groupby("product_number")["allocation_ratio"].sum()
    if any(abs(value - 1.0) > 1e-6 for value in allocation):
        errors.append("site source allocations must sum to 100% per product")
    if len(sources) > caps["max_site_product_assignments"]:
        errors.append("source assignments exceed the local profile cap")

    resource_ids = set(resources["resource_master"]["resource_id"])
    qualifications = resources["product_resource_qualification"]
    if not set(qualifications["resource_id"]) <= resource_ids:
        errors.append("a product qualification references an orphan resource")
    compatibility = resources["tester_fixture_compatibility"]
    if not set(compatibility["tester_resource_id"]) <= resource_ids:
        errors.append("tester/fixture compatibility references an unknown tester")
    if not set(compatibility["fixture_resource_id"]) <= resource_ids:
        errors.append("tester/fixture compatibility references an unknown fixture")
    resource_kind = dict(
        zip(
            resources["resource_master"]["resource_id"],
            resources["resource_master"]["resource_kind"],
            strict=True,
        )
    )
    paired_testers = set(compatibility["tester_resource_id"])
    for qualification in qualifications.to_dict("records"):
        behavior = behavior_by_product_test[
            (qualification["product_number"], qualification["test_type"])
        ]
        resource_id = qualification["resource_id"]
        if behavior == "PAIRED_FIXTURE" and resource_id not in paired_testers:
            errors.append("a paired route step lacks a compatible tester-fixture link")
            break
        if behavior == "STANDALONE" and resource_kind[resource_id] != "ACTIVE_FIXTURE":
            errors.append("a standalone route step is not assigned to an active fixture")
            break
    multi = resources["multi_dut_configuration"]
    physical_limit = multi[
        [
            "tester_channels",
            "enabled_licensed_ports",
            "tester_fixture_slots",
            "fixture_cavities",
            "handler_sockets",
        ]
    ].min(axis=1)
    if (multi["effective_parallel_duts"] > physical_limit).any():
        errors.append("multi-DUT effective capacity exceeds a physical or licensed limit")

    projections = estimate_rows(config)
    for table_name, cap_name in (
        ("machine_execution", "max_execution_rows"),
        ("machine_test_param", "max_test_parameter_rows"),
        ("machine_logs", "max_log_rows"),
    ):
        if projections[table_name] > caps[cap_name]:
            errors.append(
                f"{table_name} projection {projections[table_name]:,} exceeds cap "
                f"{caps[cap_name]:,}"
            )
    if projections["estimated_raw_bytes"] > caps["max_raw_bytes"]:
        errors.append("estimated Raw bytes exceed the configured 3 GB gate")

    if errors:
        raise ValueError("Generator preflight failed:\n- " + "\n- ".join(errors))
    return {
        "status": "passed",
        "errors": [],
        "projections": projections,
        "count_checks": count_checks,
    }
