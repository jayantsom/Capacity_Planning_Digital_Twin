"""API contracts for the Data Operations workspace."""

from fastapi.testclient import TestClient

from data_operations.backend import main

client = TestClient(main.app)


def test_workspace_and_configuration_are_available() -> None:
    """Expose one UI with the three approved generator profiles."""
    assert client.get("/data-operations/").status_code == 200
    response = client.get("/data-operations/api/config")
    assert response.status_code == 200
    assert response.json()["profiles"] == ["small", "medium", "full"]


def test_invalid_date_order_is_rejected() -> None:
    """Reject a forecast period that overlaps actual history."""
    response = client.post(
        "/data-operations/api/estimate",
        json={
            "actual_start": "2026-01-01",
            "actual_end": "2026-10-31",
            "forecast_start": "2026-10-01",
            "forecast_end": "2027-12-31",
            "plan_as_of_dates": ["2026-10-31"],
        },
    )
    assert response.status_code == 422


def test_browser_write_rejects_an_unapproved_origin() -> None:
    """Keep local compute actions unavailable to foreign web pages."""
    response = client.post(
        "/data-operations/api/jobs/pipeline",
        headers={"Origin": "https://example.invalid"},
        json={"command": "run"},
    )
    assert response.status_code == 403


def test_health_does_not_expose_the_runtime_path(monkeypatch) -> None:
    """Return operational facts without publishing a local filesystem path."""
    monkeypatch.setattr(
        main,
        "health_payload",
        lambda: {
            "status": "degraded",
            "raw_database_count": 0,
            "active_run_id": None,
            "promoted_at": None,
            "java_available": True,
        },
    )
    response = client.get("/data-operations/api/health")
    assert response.status_code == 200
    assert "runtime_home" not in response.json()


def test_clear_raw_requires_exact_confirmation(monkeypatch) -> None:
    """Reject a destructive request without the exact phrase."""
    monkeypatch.setattr(main.GLOBAL_JOBS, "active", lambda: None)
    response = client.post(
        "/data-operations/api/data/clear-raw",
        json={"confirmation": "clear raw"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Type CLEAR RAW to confirm"


def test_clear_all_is_blocked_while_compute_is_running(monkeypatch) -> None:
    """Do not delete data while a compute job may be using it."""
    monkeypatch.setattr(
        main.GLOBAL_JOBS,
        "active",
        lambda: {"job_id": "job-1", "status": "RUNNING"},
    )
    response = client.post(
        "/data-operations/api/data/clear-all",
        json={"confirmation": "CLEAR ALL"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "A compute job is running"


def test_clear_all_returns_the_clear_result(monkeypatch) -> None:
    """Return a simple removal summary after a confirmed clear."""
    monkeypatch.setattr(main.GLOBAL_JOBS, "active", lambda: None)
    monkeypatch.setattr(
        main,
        "clear_all_data",
        lambda: {
            "message": "All generated data cleared",
            "removed_files": 3,
            "removed_bytes": 100,
        },
    )
    response = client.post(
        "/data-operations/api/data/clear-all",
        json={"confirmation": "CLEAR ALL"},
    )

    assert response.status_code == 200
    assert response.json()["removed_files"] == 3
