"""Fast tests for immutable candidates, promotion, retry safety, and rollback."""

import json
from pathlib import Path

import duckdb

from data_operations.pipeline.pipeline.run_state import PipelineRun, rollback


def _config(runtime_home: Path) -> dict:
    return {
        "paths": {"runtime_home": str(runtime_home)},
        "capacity": {"default_utilization": 0.85},
    }


def _publish_inputs(runtime_home: Path) -> None:
    """Create the immutable source pointers required by a pipeline candidate."""
    (runtime_home / "raw_current.json").write_text(
        json.dumps(
            {
                "run_id": "raw-test",
                "source_control_run_id": "control-test",
                "source_control_sha256": "control-sha",
            }
        ),
        encoding="utf-8",
    )
    (runtime_home / "control_current.json").write_text(
        json.dumps(
            {
                "control_run_id": "control-test",
                "sha256": "control-sha",
                "catalog_version": "test",
            }
        ),
        encoding="utf-8",
    )


def _seal_minimal_run(candidate: PipelineRun) -> None:
    for layer in ("bronze", "silver", "gold", "serving"):
        staging = candidate.paths.database(layer, staging=True)
        with duckdb.connect(str(staging)) as connection:
            connection.execute("CREATE TABLE ready(value INTEGER)")
            connection.execute("INSERT INTO ready VALUES (1)")
        candidate.validate_database(layer, ["ready"])


def test_promotion_is_atomic_and_rollback_restores_previous(tmp_path: Path) -> None:
    """Keep a complete previous run available by changing only current.json."""
    _publish_inputs(tmp_path)
    first = PipelineRun(_config(tmp_path))
    _seal_minimal_run(first)
    first.promote()

    second = PipelineRun(_config(tmp_path))
    _seal_minimal_run(second)
    second.promote()

    pointer = json.loads((tmp_path / "current.json").read_text(encoding="utf-8"))
    assert pointer["active_run_id"] == second.paths.run_id
    assert pointer["previous_run_id"] == first.paths.run_id

    restored = rollback(tmp_path)
    pointer = json.loads((tmp_path / "current.json").read_text(encoding="utf-8"))
    assert restored == first.paths.run_id
    assert pointer["active_run_id"] == first.paths.run_id
    assert pointer["previous_run_id"] == second.paths.run_id
    first_manifest = json.loads(first.paths.manifest.read_text(encoding="utf-8"))
    second_manifest = json.loads(second.paths.manifest.read_text(encoding="utf-8"))
    assert first_manifest["active"] is True
    assert second_manifest["active"] is False


def test_failed_candidate_never_changes_active_pointer(tmp_path: Path) -> None:
    """A candidate failure must leave the known-good reader pointer untouched."""
    _publish_inputs(tmp_path)
    active = PipelineRun(_config(tmp_path))
    _seal_minimal_run(active)
    active.promote()
    pointer_before = (tmp_path / "current.json").read_bytes()

    failed = PipelineRun(_config(tmp_path))
    failed.fail("silver", RuntimeError("quality gate"))

    assert (tmp_path / "current.json").read_bytes() == pointer_before
    manifest = json.loads(failed.paths.manifest.read_text(encoding="utf-8"))
    assert manifest["status"] == "FAILED"
