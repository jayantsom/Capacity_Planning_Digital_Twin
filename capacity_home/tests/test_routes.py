"""Route checks for the combined local web application."""

from fastapi.testclient import TestClient

from capacity_home.main import app

client = TestClient(app)


def test_home_shows_four_application_cards_in_the_approved_order() -> None:
    """Keep the application launcher compact and predictable."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.text.count("data-app=") == 4
    labels = [
        "Data Explorer",
        "Decision Intelligence",
        "Operations Assistant",
        "Data Operations",
    ]
    positions = [response.text.index(label) for label in labels]
    assert positions == sorted(positions)


def test_user_interfaces_share_one_fastapi_application() -> None:
    """Serve every tool without requiring another local server."""
    assert client.get("/operations-assistant/").status_code == 200
    assert client.get("/explorer/").status_code == 200
    assert client.get("/decision-intelligence/").status_code == 200
    assert client.get("/data-operations/").status_code == 200
    assert client.get("/shared/dashboard.js").status_code == 200


def test_operations_assistant_routes_are_namespaced_without_legacy_aliases() -> None:
    """Expose only the Operations Assistant identity and route namespace."""
    route_paths = {getattr(route, "path", "") for route in app.router.routes}
    assert "/operations-assistant/" in route_paths
    assert "/operations-assistant/api/health" in route_paths
    assert "/operations-assistant/static" in route_paths
    assert "/api/health" not in route_paths
    assert "/static" not in route_paths
    assert client.get("/capacity-assistant/", follow_redirects=False).status_code == 404
