"""Golden demand checks for parent assembly and independently sold children."""

import pandas as pd

from data_operations.generator.services.demand_reconciliation import build_demand_requirements


def test_dependent_and_independent_child_demand_reconcile() -> None:
    independent = pd.DataFrame(
        [
            {
                "snapshot_id": "snap",
                "snapshot_date": "2026-10-31",
                "month_key": 202611,
                "site": "ASSEMBLY",
                "product_number": "PARENT",
                "quantity": 100,
                "knowledge_type": "FORECAST",
            },
            {
                "snapshot_id": "snap",
                "snapshot_date": "2026-10-31",
                "month_key": 202611,
                "site": "CHILD_SITE",
                "product_number": "CHILD",
                "quantity": 20,
                "knowledge_type": "FORECAST",
            },
        ]
    )
    bom = pd.DataFrame(
        [
            {
                "parent_product_number": "PARENT",
                "child_product_number": "CHILD",
                "quantity_per_parent": 2,
            }
        ]
    )
    sources = pd.DataFrame(
        [{"product_number": "CHILD", "site_code": "CHILD_SITE", "allocation_ratio": 1.0}]
    )

    demand = build_demand_requirements(independent, bom, sources)
    child = demand[demand["product_number"] == "CHILD"]

    assert set(child["demand_class"]) == {
        "DIRECT_CUSTOMER",
        "SPARE",
        "SERVICE",
        "BOM_DEPENDENT",
    }
    assert child["independent_quantity"].sum() == 20
    assert child["dependent_quantity"].sum() == 200
    assert child["total_requirement"].sum() == 220
    assert set(child["knowledge_type"]) == {"FORECAST"}
