"""Route checks for the combined local web application."""

from fastapi.testclient import TestClient

from capacity_home.main import COMPOSED_ROUTE_PATHS, app

client = TestClient(app)


def test_home_uses_registry_driven_application_cards() -> None:
    """Keep launcher content owned by the typed application registry."""
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="applicationCards"' in response.text
    registry = client.get("/shared/api/applications").json()["applications"]
    assert [item["app_id"] for item in registry if item["enabled"] and item["show_on_home"]] == [
        "data-explorer",
        "capacity-analysis",
        "decision-intelligence",
        "scenario-planning",
        "demand-supply-planning",
        "npi-ramp-planning",
        "operations-flow",
        "data-operations",
        "documentation",
    ]


def test_user_interfaces_share_one_fastapi_application() -> None:
    """Serve every tool without requiring another local server."""
    assert client.get("/operations-assistant/").status_code == 404
    assert client.get("/explorer/").status_code == 200
    assert client.get("/capacity-analysis/").status_code == 200
    assert client.get("/decision-intelligence/").status_code == 200
    assert client.get("/scenario-planning/").status_code == 200
    assert client.get("/demand-supply-planning/").status_code == 200
    assert client.get("/npi-ramp-planning/").status_code == 200
    assert client.get("/operations-flow/").status_code == 200
    assert client.get("/data-operations/").status_code == 200
    assert client.get("/documentation/").status_code == 200
    assert client.get("/shared/static/dashboard.js").status_code == 200


def test_yukti_is_shared_without_a_standalone_page() -> None:
    """Expose Yukti as a shared widget API only."""
    route_paths = set(COMPOSED_ROUTE_PATHS)
    assert "/shared/api/yukti/health" in route_paths
    assert "/shared/api/yukti/chat/stream" in route_paths
    assert "/operations-assistant/" not in route_paths
    assert "/operations-assistant/static" not in route_paths
    assert "/api/health" not in route_paths
    assert "/static" not in route_paths
    assert client.get("/capacity-assistant/", follow_redirects=False).status_code == 404
