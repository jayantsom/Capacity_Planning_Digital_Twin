"""Catalog-level checks for the bounded local telecom profile."""

from capacity_twin_core.runtime.database_paths import load_config
from data_operations.generator.catalogs.contract_tables import (
    build_resource_contracts,
    build_routes,
)
from data_operations.generator.generators.assignment_matrix import ASSIGNMENT_MATRIX
from data_operations.generator.generators.product_master import PRODUCTS
from data_operations.generator.generators.reference_data import SITES
from data_operations.generator.rules.contracts import RESOURCE_SCENARIOS
from data_operations.generator.validations.preflight import validate_preflight


def test_local_profile_passes_preflight() -> None:
    report = validate_preflight(load_config())
    assert report["status"] == "passed"
    assert report["projections"]["machine_execution"] <= 3_000_000


def test_catalog_uses_erivon_and_sparse_assignments() -> None:
    rendered_sites = " ".join(str(site) for site in SITES)
    assert "Erivon" in rendered_sites
    assert "Eric" + "sson" not in rendered_sites
    assert all(site[0].startswith("ERV_") or site[3] != "Erivon" for site in SITES)
    assert len(ASSIGNMENT_MATRIX) <= 120


def test_every_parent_and_child_has_a_separate_route() -> None:
    route_df, step_df = build_routes()
    assert set(route_df["product_number"]) == {product[0] for product in PRODUCTS}
    assert {"PARENT", "CHILD"} <= set(route_df["product_level"])
    assert (
        step_df.groupby("route_id")["step_sequence"]
        .apply(list)
        .map(lambda values: values == list(range(1, len(values) + 1)))
        .all()
    )


def test_all_capacity_behaviors_are_connected() -> None:
    _, steps = build_routes()
    assert set(steps["capacity_behavior"]) == set(RESOURCE_SCENARIOS)


def test_multi_dut_capacity_never_exceeds_a_limit() -> None:
    configurations = build_resource_contracts()["multi_dut_configuration"]
    physical = configurations[
        [
            "tester_channels",
            "enabled_licensed_ports",
            "tester_fixture_slots",
            "fixture_cavities",
            "handler_sockets",
        ]
    ].min(axis=1)
    assert (configurations["effective_parallel_duts"] <= physical).all()
