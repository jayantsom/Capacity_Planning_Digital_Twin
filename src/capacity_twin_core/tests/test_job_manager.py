"""Safety checks for the shared local job registry."""

import json
import threading

import pytest

from capacity_twin_core.jobs.manager import JobConflict, JobRegistry


def test_only_one_heavy_job_can_run(monkeypatch, tmp_path) -> None:
    """Reject a second job while the first job owns the local compute slot."""
    monkeypatch.setenv("CAPACITY_TWIN_HOME", str(tmp_path))
    registry = JobRegistry()
    started = threading.Event()
    release = threading.Event()

    def runner(report):
        report(10, "Working", "The first job owns the slot")
        started.set()
        release.wait(timeout=2)
        return {"ok": True}

    first = registry.start("first", runner)
    assert started.wait(timeout=1)
    with pytest.raises(JobConflict):
        registry.start("second", lambda _report: {})
    release.set()
    registry._threads[first["job_id"]].join(timeout=2)


def test_stale_running_job_is_marked_interrupted(monkeypatch, tmp_path) -> None:
    """Close a persisted running state after an application restart."""
    monkeypatch.setenv("CAPACITY_TWIN_HOME", str(tmp_path))
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    status = {
        "job_id": "old-job",
        "kind": "pipeline",
        "status": "RUNNING",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    (jobs / "old-job.json").write_text(json.dumps(status), encoding="utf-8")

    recovered = JobRegistry().history()
    assert recovered[0]["status"] == "INTERRUPTED"
    assert recovered[0]["completed_at"]
