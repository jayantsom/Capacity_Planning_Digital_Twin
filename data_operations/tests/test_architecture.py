"""Contracts for the metadata-driven Data Architecture workspace."""

from fastapi.testclient import TestClient

from data_operations.backend.architecture import architecture_payload
from data_operations.backend.main import app
from data_operations.pipeline.pipeline.gold.serving_views import SERVING_VIEWS

client = TestClient(app)


def test_architecture_covers_every_publication_layer() -> None:
    payload = architecture_payload()
    assert payload["layers"] == [
        "raw",
        "reference",
        "mapping",
        "bronze",
        "silver",
        "gold",
        "serving",
        "ml",
    ]
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert set(SERVING_VIEWS).issubset(nodes)
    assert "gold_gcm_base" in nodes
    assert "ml_model_registry" in nodes
    assert nodes["raw_demand.db.demand_requirement"]["catalog_source"] == "raw_raw_demand"


def test_every_lineage_edge_resolves_to_a_declared_node() -> None:
    payload = architecture_payload()
    nodes = {node["id"] for node in payload["nodes"]}
    for edge in payload["edges"]:
        assert edge["source"] in nodes
        assert edge["target"] in nodes


def test_architecture_endpoint_and_workspace_are_available() -> None:
    response = client.get("/data-operations/api/architecture")
    assert response.status_code == 200
    assert response.json()["contract_version"] == "1.0"
    html = client.get("/data-operations/").text
    assert 'data-tab="architecture"' in html
    assert 'id="architectureGraph"' in html
    assert "LINEAGE · SCHEMA · FORMULAS" in html
