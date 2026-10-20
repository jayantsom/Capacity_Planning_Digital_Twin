"""API contracts for the Decision Intelligence workspace."""

from fastapi.testclient import TestClient

from decision_intelligence.backend import main, service

client = TestClient(main.app)


def test_workspace_exposes_five_stable_workflows() -> None:
    """Keep one dashboard tab for every existing ML workflow."""
    assert client.get("/decision-intelligence/").status_code == 200
    response = client.get("/decision-intelligence/api/workflows")
    assert response.status_code == 200
    assert len(response.json()["workflows"]) == 5


def test_dashboard_rejects_an_unknown_workflow() -> None:
    """Allow only declared dashboard queries."""
    response = client.get("/decision-intelligence/api/dashboard/not-a-workflow")
    assert response.status_code == 404


def test_dashboard_rejects_a_reversed_month_range() -> None:
    """Keep dashboard time filters internally consistent."""
    response = client.get(
        "/decision-intelligence/api/dashboard/demand?month_from=202701&month_to=202601"
    )
    assert response.status_code == 422


def test_dashboard_returns_only_service_payload(monkeypatch) -> None:
    """Pass validated filters to the allowlisted query service."""
    monkeypatch.setattr(
        main,
        "dashboard",
        lambda *_args, **_kwargs: {
            "kpis": {"rows": 1},
            "series": [],
            "rankings": [],
            "rows": [],
        },
    )
    response = client.get(
        "/decision-intelligence/api/dashboard/demand?site=ERV-IN-01&limit=10"
    )
    assert response.status_code == 200
    assert response.json()["kpis"]["rows"] == 1


def test_dashboard_reports_missing_publication_without_server_error(
    monkeypatch, tmp_path
) -> None:
    """Show a controlled empty state before the first ML run."""
    monkeypatch.setattr(
        service,
        "published_database_path",
        lambda: tmp_path / "missing.duckdb",
    )
    response = client.get("/decision-intelligence/api/dashboard/demand")
    assert response.status_code == 503
    assert response.json()["detail"] == "No ML publication. Run the ML workflows first."


def test_browser_job_rejects_an_unapproved_origin() -> None:
    """Prevent foreign web pages from starting local model training."""
    response = client.post(
        "/decision-intelligence/api/jobs",
        headers={"Origin": "https://example.invalid"},
        json={"priorities": [1]},
    )
    assert response.status_code == 403
