"""Stage a complete Raw candidate and publish validated files atomically."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capacity_twin_core.runtime.database_paths import get_raw_run_pointer
from data_operations.generator.rules.determinism import stable_id


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Replace a small JSON pointer without exposing a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def create_candidate(config: dict[str, Any]) -> tuple[str, Path]:
    """Create an external run directory for candidate Raw databases."""
    run_id = stable_id(
        "generator-run",
        config["data_generation"]["random_seed"],
        config["data_generation"]["volume"],
        datetime.now(UTC).isoformat(),
    )
    runtime_home = Path(config["paths"]["runtime_home"])
    candidate = runtime_home / "artifacts" / run_id / "raw"
    candidate.mkdir(parents=True, exist_ok=False)
    return run_id, candidate


def publish_candidate(
    run_id: str,
    candidate_dir: Path,
    final_dir: Path,
    config: dict[str, Any],
    validation_report: dict[str, Any],
    preflight_report: dict[str, Any],
) -> Path:
    """Replace all ten databases with rollback if any file operation fails."""
    final_dir.mkdir(parents=True, exist_ok=True)
    rollback_dir = candidate_dir.parent / "rollback"
    rollback_dir.mkdir(parents=True, exist_ok=True)
    database_names = list(config["databases"]["raw"].values())
    replaced: list[str] = []
    try:
        for filename in database_names:
            final_path = final_dir / filename
            if final_path.exists():
                shutil.copy2(final_path, rollback_dir / filename)
            publish_temp = final_dir / f".{filename}.{run_id}.tmp"
            shutil.copy2(candidate_dir / filename, publish_temp)
            os.replace(publish_temp, final_path)
            replaced.append(filename)
    except Exception:
        for filename in replaced:
            backup = rollback_dir / filename
            if backup.exists():
                os.replace(backup, final_dir / filename)
            else:
                (final_dir / filename).unlink(missing_ok=True)
        for filename in database_names:
            (final_dir / f".{filename}.{run_id}.tmp").unlink(missing_ok=True)
        raise

    manifest = {
        "run_id": run_id,
        "schema_version": "raw-telecom-2.0",
        "catalog_version": "telecom-1.0",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "seed": config["data_generation"]["random_seed"],
        "volume": config["data_generation"]["volume"],
        "date_contract": {
            key: config["data_generation"][key]
            for key in (
                "start_date_actual",
                "end_date_actual",
                "start_date_forecast",
                "end_date_forecast",
                "snapshot_dates",
            )
        },
        "preflight": preflight_report,
        "validation": validation_report,
        "promotion_state": "published",
    }
    manifest_path = candidate_dir.parent / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    truth_manifest = {
        "run_id": run_id,
        "noise_profile": config["data_generation"]["noise_profile"],
        "declared_noise_rules": config["noise"]["allowed_rule_ids"],
        "expected_silver_disposition": {
            "RAW_DUPLICATE_EXECUTION": "DEDUPLICATE_BY_EVENT_ID",
            "RAW_MISSING_EXECUTION": "REPORT_COVERAGE_GAP",
            "RAW_NULL_MEASUREMENT": "QUARANTINE_OR_IMPUTE_WITH_FLAG",
            "RAW_TEST_TIME_OUTLIER": "RETAIN_WITH_OUTLIER_FLAG",
        },
    }
    (candidate_dir.parent / "truth_manifest.json").write_text(
        json.dumps(truth_manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    runtime_home = Path(config["paths"]["runtime_home"]).resolve()
    _atomic_json(
        get_raw_run_pointer(runtime_home),
        {
            "run_id": run_id,
            "generated_at_utc": manifest["generated_at_utc"],
            "manifest": str(manifest_path.relative_to(runtime_home)),
        },
    )
    return manifest_path
