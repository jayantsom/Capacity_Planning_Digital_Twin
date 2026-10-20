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
        "Capacity Assistant",
        "Data Operations",
    ]
    positions = [response.text.index(label) for label in labels]
    assert positions == sorted(positions)


def test_user_interfaces_share_one_fastapi_application() -> None:
    """Serve every tool without requiring another local server."""
    assert client.get("/capacity-assistant/").status_code == 200
    assert client.get("/explorer/").status_code == 200
    assert client.get("/decision-intelligence/").status_code == 200
    assert client.get("/data-operations/").status_code == 200
    assert client.get("/shared/dashboard.js").status_code == 200


def test_capacity_assistant_uses_canonical_trailing_slash() -> None:
    """Keep relative browser navigation predictable."""
    response = client.get("/capacity-assistant", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/capacity-assistant/"
