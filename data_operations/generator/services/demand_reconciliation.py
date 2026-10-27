"""Split independent demand and reconcile BOM-dependent child requirements."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from data_operations.generator.rules.determinism import stable_id

INDEPENDENT_SPLIT = {
    "DIRECT_CUSTOMER": 0.90,
    "SPARE": 0.06,
    "SERVICE": 0.04,
}


def build_demand_requirements(
    independent_totals: pd.DataFrame,
    product_bom: pd.DataFrame,
    site_product_source: pd.DataFrame,
) -> pd.DataFrame:
    """Return explicit independent and dependent demand without double counting."""
    required = {"planning_version_id", "plan_as_of_date", "month_key", "site", "product_number", "quantity"}
    missing = required - set(independent_totals.columns)
    if missing:
        raise ValueError(f"Independent demand is missing columns: {sorted(missing)}")

    rows: list[dict] = []
    for record in independent_totals.to_dict("records"):
        quantity = 0 if pd.isna(record["quantity"]) else max(0, int(record["quantity"]))
        assigned = 0
        for index, (demand_class, ratio) in enumerate(INDEPENDENT_SPLIT.items()):
            class_quantity = (
                quantity - assigned
                if index == len(INDEPENDENT_SPLIT) - 1
                else round(quantity * ratio)
            )
            assigned += class_quantity
            rows.append(
                {
                    **record,
                    "demand_id": stable_id(
                        "demand",
                        record["planning_version_id"],
                        record["month_key"],
                        record["site"],
                        record["product_number"],
                        demand_class,
                    ),
                    "demand_class": demand_class,
                    "quantity": class_quantity,
                    "parent_product_number": None,
                    "independent_quantity": class_quantity,
                    "dependent_quantity": 0,
                    "data_provenance": "SYNTHETIC_INDEPENDENT_DEMAND",
                }
            )

    parent_totals: dict[tuple, int] = defaultdict(int)
    for record in independent_totals.to_dict("records"):
        quantity = 0 if pd.isna(record["quantity"]) else max(0, int(record["quantity"]))
        parent_totals[
            (
                record["planning_version_id"],
                record["plan_as_of_date"],
                record["month_key"],
                record["product_number"],
                record.get("knowledge_type"),
            )
        ] += quantity

    source_lookup: dict[str, list[dict]] = defaultdict(list)
    for source in site_product_source.to_dict("records"):
        source_lookup[source["product_number"]].append(source)

    bom_by_parent: dict[str, list[dict]] = defaultdict(list)
    for component in product_bom.to_dict("records"):
        bom_by_parent[component["parent_product_number"]].append(component)

    for (
        planning_version_id,
        plan_as_of_date,
        month_key,
        parent,
        knowledge_type,
    ), parent_quantity in parent_totals.items():
        for component in bom_by_parent.get(parent, []):
            child = component["child_product_number"]
            child_total = parent_quantity * int(component["quantity_per_parent"])
            allocated = 0
            child_sources = source_lookup[child]
            for index, source in enumerate(child_sources):
                quantity = (
                    child_total - allocated
                    if index == len(child_sources) - 1
                    else round(child_total * float(source["allocation_ratio"]))
                )
                allocated += quantity
                rows.append(
                    {
                        "planning_version_id": planning_version_id,
                        "plan_as_of_date": plan_as_of_date,
                        "month_key": month_key,
                        "site": source["site_code"],
                        "product_number": child,
                        "demand_id": stable_id(
                            "demand", planning_version_id, month_key, source["site_code"], child, parent
                        ),
                        "demand_class": "BOM_DEPENDENT",
                        "quantity": quantity,
                        "parent_product_number": parent,
                        "knowledge_type": knowledge_type,
                        "independent_quantity": 0,
                        "dependent_quantity": quantity,
                        "data_provenance": "BOM_EXPLOSION",
                    }
                )

    demand = pd.DataFrame(rows)
    demand["total_requirement"] = demand["independent_quantity"] + demand["dependent_quantity"]
    return demand.sort_values(
        ["planning_version_id", "month_key", "product_number", "site", "demand_class", "demand_id"]
    ).reset_index(drop=True)
