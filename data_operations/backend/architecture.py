"""Metadata-driven lineage for the Data Operations architecture workspace."""

from __future__ import annotations

import re
from collections import defaultdict
from itertools import pairwise
from typing import Any

from capacity_twin_core.data.contracts import load_contract
from capacity_twin_core.runtime.analytics import ML_ALIASES
from data_operations.pipeline.pipeline.gold.serving_views import SERVING_VIEWS

LAYER_ORDER = {
    "raw": 0,
    "reference": 1,
    "mapping": 2,
    "bronze": 3,
    "silver": 4,
    "gold": 5,
    "serving": 6,
    "ml": 7,
}

GOLD_LINEAGE: dict[str, tuple[list[str], str, str]] = {
    "gold_gcm_base": (
        [
            "slvr_demand_long",
            "slvr_prod_master",
            "slvr_product_bom",
            "slvr_product_route",
            "slvr_route_step",
            "slvr_tgt_test_time_long",
            "slvr_tgt_yield_long",
            "slvr_site_equip_inv_long",
            "slvr_site_soft_long",
            "slvr_resource_contract",
        ],
        "Demand is converted to required test workload. Yield, time, calendar, and governed resource behavior are applied.",
        "site, product, test, month, planning version, resource",
    ),
    "gold_resource_scenarios": (
        ["gold_gcm_base"],
        "Calculates Normal and Maximum resource capacity for NONE, TYPE1, and TYPE2 retest modes.",
        "site, product, test, month, planning version, resource, capacity mode, retest mode",
    ),
    "gold_dmnd_vs_cap": (
        ["gold_resource_scenarios"],
        "Capacity gap = capacity quantity - effective demand quantity.",
        "site, product, test, month, planning version, resource, capacity mode, retest mode",
    ),
    "gold_bottleneck": (
        ["gold_dmnd_vs_cap"],
        "Ranks negative capacity gaps and calculates investment need by governed resource.",
        "site, test, month, planning version, resource, capacity mode, retest mode",
    ),
    "gold_operational_performance": (
        ["slvr_machine_execution", "slvr_machine_test_param"],
        "Aggregates measured yield, downtime, throughput, and OEE from execution facts.",
        "period grain, period, site, product, test",
    ),
    "gold_operational_events": (
        ["slvr_machine_logs"],
        "Counts governed machine events by operational period.",
        "period grain, period, site, product, test, event type",
    ),
    "gold_forecast_accuracy": (
        ["slvr_demand_long"],
        "Compares forecast demand with actual demand at matching business grain.",
        "site, product, month, planning version",
    ),
    "gold_cap_actual": (
        ["slvr_machine_execution"],
        "Aggregates historical tested output without a forecast planning version.",
        "site, product, test, month",
    ),
    "gold_demonstrated_capacity": (
        ["gold_cap_actual", "gold_operational_performance"],
        "Uses observed output and performance to estimate demonstrated capacity.",
        "site, product, test, month",
    ),
    "gold_ml_feature_store": (
        ["gold_gcm_base", "gold_operational_performance"],
        "Publishes point-in-time features and measured labels at the declared ML grain.",
        "site, product, test, month, planning version",
    ),
    "gold_equipment_cost_reference": (
        ["slvr_equipment_cost_reference"],
        "Publishes effective-dated equipment purchase, installation, and maintenance costs.",
        "equipment, effective interval",
    ),
}

ML_LINEAGE = {
    "ml_demand_forecast": ["srv_ml_feature_store"],
    "ml_forecast_accuracy": ["srv_ml_feature_store"],
    "ml_yield_predictions": ["srv_ml_feature_store"],
    "ml_yield_shap": ["ml_yield_predictions"],
    "ml_capacity_adjusted": ["ml_yield_predictions", "srv_gcm_resource_contract"],
    "ml_oee_degradation_risk": ["srv_ml_feature_store", "srv_oee_metrics"],
    "ml_oee_degradation_alerts": ["ml_oee_degradation_risk"],
    "ml_oee_anomalies": ["srv_ml_feature_store", "srv_oee_metrics"],
    "ml_oee_anomaly_summary": ["ml_oee_anomalies"],
    "ml_capex_summary": ["srv_gcm_resource_contract", "srv_reference_equipment"],
    "ml_capex_scenarios": ["ml_capex_summary"],
    "ml_model_registry": [],
}

REFERENCE_FLOWS = {
    "raw_site.db.site_master": (
        "reference.canonical.site",
        "mapping.bridge.site",
        "slvr_ref_site",
    ),
    "raw_product.db.product_master": (
        "reference.canonical.product",
        "mapping.bridge.product",
        "slvr_prod_master",
    ),
    "raw_test.db.test_type_master": (
        "reference.canonical.test_type",
        "mapping.bridge.test_type",
        "slvr_ref_test_type",
    ),
    "raw_machine.db.equipment_master": (
        "reference.canonical.machine",
        "mapping.bridge.machine",
        "slvr_ref_equipment",
    ),
}


def _layer(object_id: str) -> str:
    if object_id.startswith("raw_"):
        return "raw"
    if object_id.startswith("reference."):
        return "reference"
    if object_id.startswith("mapping."):
        return "mapping"
    if object_id.startswith("brnz_"):
        return "bronze"
    if object_id.startswith("slvr_"):
        return "silver"
    if object_id.startswith("gold_"):
        return "gold"
    if object_id.startswith("srv_"):
        return "serving"
    if object_id.startswith("ml_"):
        return "ml"
    return "reference"


def _catalog_location(object_id: str) -> tuple[str | None, str | None]:
    layer = _layer(object_id)
    if layer == "raw":
        parts = object_id.split(".")
        database = ".".join(parts[:2])
        table = ".".join(parts[2:])
        return f"raw_{database.removesuffix('.db')}", table
    if layer in {"bronze", "silver", "gold", "serving", "ml"}:
        return f"duckdb_{layer}", object_id
    if layer in {"reference", "mapping"}:
        prefix, schema, table = object_id.split(".", 2)
        return f"duckdb_{prefix}", f"{schema}.{table}"
    return None, None


def _sql_dependencies(sql: str) -> list[str]:
    candidates = re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)", sql)
    return sorted(
        {
            name
            for name in candidates
            if name.startswith(("brnz_", "slvr_", "gold_", "srv_", "ml_"))
        }
    )


def architecture_payload() -> dict[str, Any]:
    """Build the lineage graph from tracked contracts and publication metadata."""
    contract = load_contract("source_to_serving")
    details: dict[str, dict[str, Any]] = {}
    edge_set: set[tuple[str, str, str]] = set()

    def add_node(object_id: str, **metadata: Any) -> None:
        if object_id == "serving":
            return
        source, table = _catalog_location(object_id)
        current = details.setdefault(
            object_id,
            {
                "id": object_id,
                "label": object_id.split(".")[-1],
                "layer": _layer(object_id),
                "catalog_source": source,
                "catalog_table": table,
            },
        )
        current.update({key: value for key, value in metadata.items() if value is not None})

    def add_edge(source: str, target: str, relation: str = "transforms") -> None:
        if source != "serving" and target != "serving":
            add_node(source)
            add_node(target)
            edge_set.add((source, target, relation))

    for table_name, table_contract in contract["tables"].items():
        lineage = table_contract["lineage"]
        for object_id in lineage:
            add_node(
                object_id,
                source_contract=table_name,
                grain=table_contract["grain"],
                units=table_contract["units"],
                owner=table_contract["owner"],
                natural_keys=table_contract["natural_keys"],
                canonical_keys=table_contract["canonical_keys"],
                consuming_apps=table_contract["consuming_apps"],
            )
        for source, target in pairwise(lineage):
            add_edge(source, target)

    for source, flow in REFERENCE_FLOWS.items():
        prior = source
        for target in flow:
            add_edge(prior, target, "governs")
            prior = target

    for target, (sources, formula, grain) in GOLD_LINEAGE.items():
        add_node(target, formula=formula, grain=grain, owner="GOLD_ANALYTICS")
        for source in sources:
            add_edge(source, target, "calculates")

    for target, sql in SERVING_VIEWS.items():
        add_node(
            target,
            formula="Materialized app-facing publication. No attachment is required at read time.",
            owner="SERVING_PUBLICATION",
        )
        for source in _sql_dependencies(sql):
            add_edge(source, target, "publishes")

    for target, sources in ML_LINEAGE.items():
        add_node(
            target,
            formula="Governed ML output or model-release metadata.",
            owner="ML_PUBLICATION",
        )
        for source in sources:
            add_edge(source, target, "models")

    for table in set(ML_ALIASES.values()):
        add_node(table, owner="ML_PUBLICATION")

    nodes = sorted(
        details.values(),
        key=lambda item: (LAYER_ORDER[item["layer"]], item["id"]),
    )
    edges = [
        {"source": source, "target": target, "relation": relation}
        for source, target, relation in sorted(edge_set)
    ]
    counts = defaultdict(int)
    for node in nodes:
        counts[node["layer"]] += 1
    return {
        "contract_version": contract["contract_version"],
        "schema_version": contract["schema_version"],
        "nodes": nodes,
        "edges": edges,
        "layer_counts": dict(counts),
        "layers": list(LAYER_ORDER),
    }
