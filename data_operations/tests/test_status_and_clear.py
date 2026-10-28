"""Component status, lineage, and guarded data-clearing tests."""

import hashlib
import json
from pathlib import Path

import pytest

from capacity_twin_core.runtime.database_paths import (
    get_active_run_pointer,
    get_source_bundle_pointer,
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
    bundle = runtime / "source_bundles" / run_id
    raw_dir = bundle / "raw"
    raw_dir.mkdir(parents=True)
    for name in ("first.db", "second.db"):
        (raw_dir / name).write_bytes(b"raw")
    (bundle / "reference.duckdb").write_bytes(b"reference")
    (bundle / "mapping.duckdb").write_bytes(b"mapping")
    files = {}
    for path, role in (
        (raw_dir / "first.db", "raw"),
        (raw_dir / "second.db", "raw"),
        (bundle / "reference.duckdb", "reference"),
        (bundle / "mapping.duckdb", "mapping"),
    ):
        files[path.name] = {
            "path": str(path.relative_to(runtime)),
            "role": role,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    bundle_checksum = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = bundle / "source_bundle_manifest.json"
    _write_json(
        manifest,
        {
            "source_run_id": run_id,
            "bundle_checksum": bundle_checksum,
            "catalog_version": "test",
            "files": files,
        },
    )
    _write_json(
        get_source_bundle_pointer(runtime),
        {
            "source_run_id": run_id,
            "run_id": run_id,
            "generated_at_utc": "2026-10-20T00:00:00+00:00",
            "bundle_checksum": bundle_checksum,
            "manifest": str(manifest.relative_to(runtime)),
            "raw_directory": str(raw_dir.relative_to(runtime)),
            "reference_database": str((bundle / "reference.duckdb").relative_to(runtime)),
            "mapping_database": str((bundle / "mapping.duckdb").relative_to(runtime)),
        },
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
    source_pointer = json.loads(
        get_source_bundle_pointer(runtime).read_text(encoding="utf-8")
    )
    _write_json(
        manifest,
        {
            "run_id": run_id,
            "source_raw_run_id": source_raw_run_id,
            "source_control_run_id": source_raw_run_id,
            "source_control_sha256": source_pointer["bundle_checksum"],
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


def test_clear_raw_preserves_referenced_source_pipeline_and_records(runtime: Path) -> None:
    """Keep source data pinned by a promoted pipeline."""
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
    assert (runtime / "source_bundles" / "raw-1").exists()
    assert not generator_run.exists()
    assert (runtime / "artifacts" / "pipeline-1").is_dir()
    assert (runtime / "jobs" / "history.json").is_file()
    assert (runtime / "logs" / "app.log").is_file()


def test_clear_all_preserves_active_publications_and_operational_records(runtime: Path) -> None:
    """Remove unreferenced data while retaining active publications."""
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
    for folder in ("raw", ".staging", "models", "bronze", "silver", "gold", "serving"):
        assert not (runtime / folder).exists()
    assert (runtime / "artifacts" / "pipeline-1").exists()
    assert (runtime / "source_bundles" / "raw-1").exists()
    assert not (runtime / "ml_current.json").exists()
    assert (runtime / "jobs" / "history.json").is_file()
    assert (runtime / "logs" / "app.log").is_file()
