"""Component status, lineage, and guarded data-clearing tests."""

import json
from pathlib import Path

import pytest

from capacity_twin_core.runtime.database_paths import (
    get_active_run_pointer,
    get_raw_run_pointer,
)
from data_operations.backend import service
from data_operations.pipeline.pipeline.run_state import DATABASE_FILES


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Use a small temporary runtime for every test."""
    config = {
        "databases": {
            "raw": {"first": "first.db", "second": "second.db"},
            "bronze": "bronze.duckdb",
            "silver": "silver.duckdb",
            "gold": "gold.duckdb",
            "serving": "serving.duckdb",
        }
    }
    monkeypatch.setattr(service, "get_runtime_home", lambda: tmp_path)
    monkeypatch.setattr(service, "load_config", lambda: config)
    monkeypatch.setattr(service.GLOBAL_JOBS, "active", lambda: None)
    return tmp_path


def _write_json(path: Path, payload: dict) -> None:
    """Write one small runtime metadata file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _publish_raw(runtime: Path, run_id: str = "raw-1") -> None:
    """Create a complete two-file Raw publication."""
    raw_dir = runtime / "raw" / "sqlite"
    raw_dir.mkdir(parents=True)
    for name in ("first.db", "second.db"):
        (raw_dir / name).write_bytes(b"raw")
    _write_json(
        get_raw_run_pointer(runtime),
        {"run_id": run_id, "generated_at_utc": "2026-10-20T00:00:00+00:00"},
    )


def _publish_pipeline(
    runtime: Path,
    *,
    source_raw_run_id: str,
    run_id: str = "pipeline-1",
) -> None:
    """Create a complete promoted pipeline publication."""
    run_dir = runtime / "artifacts" / run_id
    run_dir.mkdir(parents=True)
    for name in DATABASE_FILES:
        (run_dir / name).write_bytes(b"derived")
    manifest = run_dir / "manifest.json"
    _write_json(
        manifest,
        {
            "run_id": run_id,
            "source_raw_run_id": source_raw_run_id,
            "status": "PROMOTED",
        },
    )
    _write_json(
        get_active_run_pointer(runtime),
        {
            "active_run_id": run_id,
            "manifest": str(manifest),
            "promoted_at": "2026-10-20T01:00:00+00:00",
        },
    )


def test_empty_runtime_reports_both_components_without_data(runtime: Path) -> None:
    """Show a degraded workspace until Raw and pipeline data exist."""
    health = service.health_payload()

    assert health["status"] == "degraded"
    assert health["generator"]["status"] == "no-data"
    assert health["pipeline"]["status"] == "no-data"


def test_matching_lineage_makes_data_operations_ready(runtime: Path) -> None:
    """Require the promoted pipeline to use the current Raw generation."""
    _publish_raw(runtime)
    _publish_pipeline(runtime, source_raw_run_id="raw-1")

    health = service.health_payload()

    assert health["status"] == "ready"
    assert health["generator"]["status"] == "ready"
    assert health["pipeline"]["status"] == "ready"


def test_new_raw_generation_marks_existing_pipeline_stale(runtime: Path) -> None:
    """Make a pipeline stale when its source Raw run no longer matches."""
    _publish_raw(runtime, run_id="raw-2")
    _publish_pipeline(runtime, source_raw_run_id="raw-1")

    health = service.health_payload()

    assert health["status"] == "degraded"
    assert health["pipeline"]["status"] == "stale"


def test_clear_raw_preserves_pipeline_logs_and_job_history(runtime: Path) -> None:
    """Remove Raw assets without deleting promoted output or records."""
    _publish_raw(runtime)
    generator_run = runtime / "artifacts" / "generator-run-1"
    generator_run.mkdir(parents=True)
    (generator_run / "manifest.json").write_text("{}", encoding="utf-8")
    _publish_pipeline(runtime, source_raw_run_id="raw-1")
    (runtime / "jobs").mkdir()
    (runtime / "jobs" / "history.json").write_text("[]", encoding="utf-8")
    (runtime / "logs").mkdir()
    (runtime / "logs" / "app.log").write_text("kept", encoding="utf-8")

    result = service.clear_raw_data()

    assert result["removed_files"] > 0
    assert not (runtime / "raw").exists()
    assert not generator_run.exists()
    assert (runtime / "artifacts" / "pipeline-1").is_dir()
    assert (runtime / "jobs" / "history.json").is_file()
    assert (runtime / "logs" / "app.log").is_file()


def test_clear_all_preserves_only_operational_records(runtime: Path) -> None:
    """Remove generated, pipeline, and model data while keeping records."""
    _publish_raw(runtime)
    _publish_pipeline(runtime, source_raw_run_id="raw-1")
    for folder in (".staging", "models", "bronze", "silver", "gold", "serving"):
        path = runtime / folder
        path.mkdir()
        (path / "data.bin").write_bytes(b"data")
    (runtime / "ml_current.json").write_text("{}", encoding="utf-8")
    (runtime / "jobs").mkdir()
    (runtime / "jobs" / "history.json").write_text("[]", encoding="utf-8")
    (runtime / "logs").mkdir()
    (runtime / "logs" / "app.log").write_text("kept", encoding="utf-8")

    result = service.clear_all_data()

    assert result["message"] == "All generated data cleared"
    for folder in ("raw", "artifacts", ".staging", "models", "bronze", "silver", "gold", "serving"):
        assert not (runtime / folder).exists()
    assert not (runtime / "ml_current.json").exists()
    assert (runtime / "jobs" / "history.json").is_file()
    assert (runtime / "logs" / "app.log").is_file()
