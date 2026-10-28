"""Configuration, health, and job runners for Data Operations."""

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

from capacity_twin_core.jobs import GLOBAL_JOBS
from capacity_twin_core.runtime.database_paths import (
    get_active_run_pointer,
    get_release_pointer,
    get_runtime_home,
    get_source_bundle_pointer,
    load_app_config,
    load_config,
)
from data_operations.backend.models import GeneratorOptions
from data_operations.generator.generators.run_all_generators import run_all
from data_operations.generator.validations.outputs import file_checksum
from data_operations.generator.validations.preflight import estimate_rows
from data_operations.pipeline.pipeline.run_state import DATABASE_FILES, rollback
from data_operations.pipeline.runner import run_pipeline

PROFILE_KEYS = load_app_config("data_operations")["profiles"]


def build_run_config(options: GeneratorOptions) -> dict[str, Any]:
    """Apply validated UI overrides to an in-memory run configuration."""
    config = deepcopy(load_config())
    profile_key = PROFILE_KEYS[options.profile]
    generation = config["data_generation"]
    generation.update(
        {
            "random_seed": options.random_seed,
            "volume": profile_key,
            "start_date_actual": options.actual_start.isoformat(),
            "end_date_actual": options.actual_end.isoformat(),
            "start_date_forecast": options.forecast_start.isoformat(),
            "end_date_forecast": options.forecast_end.isoformat(),
            "plan_as_of_dates": [value.isoformat() for value in options.plan_as_of_dates],
            "noise_profile": options.noise_profile,
        }
    )
    limits = config["local_16gb"]
    for field in (
        "max_active_sites",
        "max_active_products",
        "max_active_test_types",
        "max_systems",
        "max_fixtures_handlers",
    ):
        value = getattr(options, field)
        if value is not None:
            limits[field] = value
    _apply_noise_profile(config, options.noise_profile)
    return config


def estimate_run(options: GeneratorOptions) -> dict[str, Any]:
    """Return a conservative local size estimate for the selected controls."""
    config = build_run_config(options)
    limits = config["local_16gb"]
    projection = estimate_rows(config)
    total_rows = (
        projection["machine_execution"]
        + projection["machine_test_param"]
        + projection["machine_logs"]
    )
    estimated_bytes = projection["estimated_raw_bytes"]
    runtime = get_runtime_home()
    disk_probe = runtime
    while not disk_probe.exists() and disk_probe != disk_probe.parent:
        disk_probe = disk_probe.parent
    free_disk_bytes = shutil.disk_usage(disk_probe).free
    within_limits = (
        projection["machine_execution"] <= limits["max_execution_rows"]
        and projection["machine_test_param"] <= limits["max_test_parameter_rows"]
        and projection["machine_logs"] <= limits["max_log_rows"]
        and estimated_bytes <= limits["max_raw_bytes"]
        and free_disk_bytes >= limits["min_free_disk_bytes"]
    )
    return {
        "profile": options.profile,
        "estimated_rows": total_rows,
        "estimated_raw_bytes": estimated_bytes,
        "free_disk_bytes": free_disk_bytes,
        "estimated_minutes": round(
            max(
                0.2,
                limits["max_generation_minutes"]
                * projection["machine_execution"]
                / limits["max_execution_rows"],
            ),
            1,
        ),
        "within_local_limits": within_limits,
    }


def _read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object or return an empty result for an invalid file."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _path_size(path: Path) -> int:
    """Return total bytes without following external symbolic links."""
    if path.is_symlink():
        return 0
    if path.is_file():
        return path.stat().st_size
    if not path.is_dir():
        return 0
    return sum(
        child.stat().st_size
        for child in path.rglob("*")
        if child.is_file() and not child.is_symlink()
    )


def _raw_publication(runtime: Path) -> dict[str, Any]:
    """Read the unified source pointer and its immutable manifest."""
    pointer = _read_json(get_source_bundle_pointer(runtime))
    if not pointer:
        return {}
    manifest_path = Path(pointer.get("manifest", ""))
    if not manifest_path.is_absolute():
        manifest_path = runtime / manifest_path
    manifest = _read_json(manifest_path)
    return {**pointer, "manifest_path": str(manifest_path), "manifest_data": manifest}


def _pipeline_publication(runtime: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read the promoted pipeline pointer and its manifest."""
    pointer = _read_json(get_active_run_pointer(runtime))
    manifest_path = Path(pointer.get("manifest", "")) if pointer.get("manifest") else None
    if manifest_path and not manifest_path.is_absolute():
        manifest_path = runtime / manifest_path
    manifest = _read_json(manifest_path) if manifest_path else {}
    return pointer, manifest


def _control_publication(runtime: Path) -> dict[str, Any]:
    """Return Reference and Mapping paths from the captured source bundle."""
    pointer = _raw_publication(runtime)
    if not pointer:
        return {}
    paths = {}
    for key in ("reference_database", "mapping_database"):
        path = Path(pointer.get(key, ""))
        if not path.is_absolute():
            path = runtime / path
        if not path.is_file():
            return {}
        paths[key] = str(path)
    return {
        **pointer,
        **paths,
        "control_run_id": pointer.get("source_run_id"),
        "sha256": pointer.get("bundle_checksum"),
        "catalog_version": pointer.get("manifest_data", {}).get("catalog_version"),
        "promoted_at": pointer.get("generated_at_utc"),
    }


def _raw_clear_targets(runtime: Path) -> list[Path]:
    """List unreferenced Raw paths while preserving captured releases."""
    protected = _protected_run_ids(runtime)
    return [
        runtime / "raw",
        *(runtime / "artifacts").glob("generator-run-*"),
        *(
            path
            for path in (runtime / "source_bundles").glob("*")
            if path.name not in protected["source"]
        ),
    ]


def _all_clear_targets(runtime: Path) -> list[Path]:
    """List removable data while retaining active and rollback publications."""
    config = load_config()
    protected = _protected_run_ids(runtime)
    return [
        runtime / "raw",
        runtime / ".staging",
        runtime / "models",
        runtime / "control",
        *(
            path
            for path in (runtime / "source_bundles").glob("*")
            if path.name not in protected["source"]
        ),
        *(
            path
            for path in (runtime / "artifacts").glob("*")
            if path.name not in protected["pipeline"]
        ),
        *(runtime / layer for layer in ("bronze", "silver", "gold", "serving")),
        *(
            runtime / config["databases"][layer]
            for layer in ("bronze", "silver", "gold", "serving")
        ),
        runtime / "ml_current.json",
    ]


def _protected_run_ids(runtime: Path) -> dict[str, set[str]]:
    """Return source and pipeline run IDs pinned by active or rollback pointers."""
    source: set[str] = set()
    pipeline: set[str] = set()
    source_pointer = _read_json(get_source_bundle_pointer(runtime))
    if source_pointer.get("source_run_id"):
        source.add(str(source_pointer["source_run_id"]))
    release = _read_json(get_release_pointer(runtime))
    release_source = release.get("source_bundle", {})
    if isinstance(release_source, dict) and release_source.get("run_id"):
        source.add(str(release_source["run_id"]))
    active = _read_json(get_active_run_pointer(runtime))
    for key in ("active_run_id", "previous_run_id"):
        if active.get(key):
            pipeline.add(str(active[key]))
    for run_id in list(pipeline):
        manifest = _read_json(runtime / "artifacts" / run_id / "manifest.json")
        if manifest.get("source_bundle_run_id"):
            source.add(str(manifest["source_bundle_run_id"]))
    return {"source": source, "pipeline": pipeline}


def _data_size(runtime: Path) -> int:
    """Measure all generated data while excluding logs and job history."""
    config = load_config()
    targets = [
        runtime / "source_bundles",
        runtime / "artifacts",
        runtime / "raw",
        runtime / ".staging",
        runtime / "models",
        runtime / "control",
        *(runtime / layer for layer in ("bronze", "silver", "gold", "serving")),
        *(
            runtime / config["databases"][layer]
            for layer in ("bronze", "silver", "gold", "serving")
        ),
    ]
    return sum(_path_size(path) for path in targets)


def health_payload() -> dict[str, Any]:
    """Report control, Raw, and pipeline readiness with exact lineage."""
    runtime = get_runtime_home()
    config = load_config()
    raw_publication = _raw_publication(runtime)
    raw_dir_value = raw_publication.get("raw_directory")
    raw_dir = Path(raw_dir_value) if raw_dir_value else runtime / "raw" / "sqlite"
    if not raw_dir.is_absolute():
        raw_dir = runtime / raw_dir
    raw_files = sorted(raw_dir.glob("*.db")) if raw_dir.is_dir() else []
    expected_raw = set(config["databases"]["raw"].values())
    available_raw = {path.name for path in raw_files}
    raw_complete = expected_raw.issubset(available_raw)
    control_publication = _control_publication(runtime)
    control_run_id = control_publication.get("control_run_id")
    control_sha256 = control_publication.get("sha256")
    control_status = "ready" if control_publication else "no-data"
    raw_run_id = raw_publication.get("source_run_id")
    manifest_data = raw_publication.get("manifest_data", {})
    canonical_checksum = hashlib.sha256(
        json.dumps(
            manifest_data.get("files", {}), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    source_files_valid = bool(
        manifest_data
        and manifest_data.get("bundle_checksum")
        == raw_publication.get("bundle_checksum")
        == canonical_checksum
    )
    for details in manifest_data.get("files", {}).values():
        path = Path(details.get("path", ""))
        if not path.is_absolute():
            path = runtime / path
        if (
            not path.is_file()
            or not details.get("sha256")
            or file_checksum(path) != details["sha256"]
        ):
            source_files_valid = False
            break
    raw_matches_control = bool(
        control_run_id
        and raw_run_id == control_run_id
        and raw_publication.get("bundle_checksum") == control_sha256
    )
    if not raw_complete:
        generator_status = "no-data" if not raw_files else "failed"
    elif not raw_run_id or not raw_matches_control or not source_files_valid:
        generator_status = "stale"
    else:
        generator_status = "ready"

    pipeline_pointer, pipeline_manifest = _pipeline_publication(runtime)
    active_run_id = pipeline_pointer.get("active_run_id")
    pipeline_dir = runtime / "artifacts" / str(active_run_id)
    pipeline_complete = bool(
        active_run_id
        and pipeline_manifest
        and all((pipeline_dir / filename).is_file() for filename in DATABASE_FILES)
    )
    source_raw_run_id = pipeline_manifest.get("source_raw_run_id")
    source_control_run_id = pipeline_manifest.get("source_control_run_id")
    source_control_sha256 = pipeline_manifest.get("source_control_sha256")
    pipeline_matches_lineage = bool(
        raw_run_id
        and control_run_id
        and source_raw_run_id == raw_run_id
        and source_control_run_id == control_run_id
        and source_control_sha256 == control_sha256
    )
    if not pipeline_complete:
        pipeline_status = "no-data" if not active_run_id else "failed"
    elif generator_status != "ready" or control_status != "ready" or not pipeline_matches_lineage:
        pipeline_status = "stale"
    else:
        pipeline_status = "ready"

    active_job = GLOBAL_JOBS.active()
    if active_job and active_job.get("kind") in {"generator", "pipeline", "rebuild"}:
        kind = active_job["kind"]
        if kind in {"generator", "rebuild"}:
            control_status = "running"
            generator_status = "running"
        if kind in {"pipeline", "rebuild"}:
            pipeline_status = "running"
        overall_status = "running"
    else:
        overall_status = (
            "ready"
            if control_status == generator_status == pipeline_status == "ready"
            else "degraded"
        )

    previous_run_id = pipeline_pointer.get("previous_run_id")
    rollback_available = bool(
        previous_run_id
        and (runtime / "artifacts" / str(previous_run_id) / "manifest.json").is_file()
    )
    all_targets = _all_clear_targets(runtime)
    source_bundle_root = raw_dir.parent if raw_dir.name == "raw" else raw_dir
    raw_size = _path_size(source_bundle_root)
    raw_file_count = _file_count(source_bundle_root)
    total_file_count = sum(_file_count(path) for path in all_targets)
    return {
        "status": overall_status,
        "liveness": {"status": "live"},
        "readiness": {
            "status": "ready" if overall_status == "ready" else "not-ready",
            "source_checksums_valid": source_files_valid,
            "source_run_id": raw_run_id,
        },
        "freshness": {
            "status": "current" if generator_status == "ready" else "unknown",
            "generated_at": raw_publication.get("generated_at_utc"),
        },
        "optional_dependencies": {
            "java": "available" if shutil.which("java") is not None else "unavailable"
        },
        "control": {
            "status": control_status,
            "run_id": control_run_id,
            "catalog_version": control_publication.get("catalog_version"),
            "published_at": control_publication.get("promoted_at"),
            "reference_database": control_publication.get("reference_database"),
            "mapping_database": control_publication.get("mapping_database"),
            "sha256": control_sha256,
        },
        "generator": {
            "status": generator_status,
            "run_id": raw_run_id,
            "generated_at": raw_publication.get("generated_at_utc"),
            "database_count": len(raw_files),
            "expected_database_count": len(expected_raw),
            "size_bytes": raw_size,
        },
        "pipeline": {
            "status": pipeline_status,
            "run_id": active_run_id,
            "source_raw_run_id": source_raw_run_id,
            "source_control_run_id": source_control_run_id,
            "source_control_sha256": source_control_sha256,
            "promoted_at": pipeline_pointer.get("promoted_at"),
            "rollback_available": rollback_available,
            "size_bytes": _path_size(pipeline_dir) if active_run_id else 0,
        },
        "raw_database_count": len(raw_files),
        "active_run_id": active_run_id,
        "promoted_at": pipeline_pointer.get("promoted_at"),
        "raw_file_count": raw_file_count,
        "raw_size_bytes": raw_size,
        "total_file_count": total_file_count,
        "total_data_size_bytes": _data_size(runtime),
        "rollback_available": rollback_available,
        "java_available": shutil.which("java") is not None,
    }


def promoted_run_payload() -> dict[str, Any]:
    """Return safe manifest details for the active medallion run."""
    runtime = get_runtime_home().resolve()
    pointer = get_active_run_pointer(runtime)
    if not pointer.is_file():
        raise FileNotFoundError("No promoted pipeline run")
    active = json.loads(pointer.read_text(encoding="utf-8"))
    manifest_path = Path(active["manifest"]).resolve()
    if runtime not in manifest_path.parents:
        raise ValueError("Pipeline manifest escapes the runtime home")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "active_run_id": active.get("active_run_id"),
        "previous_run_id": active.get("previous_run_id"),
        "promoted_at": active.get("promoted_at"),
        "status": manifest.get("status"),
        "source_raw_run_id": manifest.get("source_raw_run_id"),
        "source_control_run_id": manifest.get("source_control_run_id"),
        "source_control_sha256": manifest.get("source_control_sha256"),
        "stages": manifest.get("stages", {}),
        "validations": manifest.get("validations", []),
        "files": {
            name: {
                "sha256": details.get("sha256"),
                "size_bytes": details.get("size_bytes"),
            }
            for name, details in manifest.get("files", {}).items()
        },
    }


def run_generator(options: GeneratorOptions, report) -> dict[str, Any]:
    """Run the generator with one validated override configuration."""
    return run_all(build_run_config(options), progress_callback=report)


def run_pipeline_job(report) -> dict[str, Any]:
    """Build and promote all medallion layers."""
    candidate = run_pipeline(load_config(), progress_callback=report)
    return {
        "run_id": candidate.paths.run_id,
        "manifest": str(candidate.paths.manifest),
    }


def run_rebuild(options: GeneratorOptions, report) -> dict[str, Any]:
    """Generate Raw data, then build the complete medallion pipeline."""

    def generator_progress(progress: int, phase: str, detail: str) -> None:
        report(max(1, progress // 2), f"Generator · {phase}", detail)

    generator_result = run_generator(options, generator_progress)

    def pipeline_progress(progress: int, phase: str, detail: str) -> None:
        report(50 + progress // 2, f"Pipeline · {phase}", detail)

    candidate = run_pipeline(build_run_config(options), progress_callback=pipeline_progress)
    return {
        "generator": generator_result,
        "pipeline_run_id": candidate.paths.run_id,
        "pipeline_manifest": str(candidate.paths.manifest),
    }


def rollback_pipeline() -> str:
    """Activate the previous validated pipeline run."""
    return rollback(get_runtime_home())


def _file_count(path: Path) -> int:
    """Count files that belong to one removable path."""
    if path.is_file() or path.is_symlink():
        return 1
    if not path.is_dir():
        return 0
    return sum(1 for child in path.rglob("*") if child.is_file())


def _remove_path(path: Path, runtime: Path) -> tuple[int, int]:
    """Remove one known runtime path and report files and bytes."""
    if path.parent != runtime and runtime not in path.parents:
        raise ValueError("Refusing to remove a path outside the runtime directory")
    count = _file_count(path)
    size = _path_size(path)
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)
    return count, size


def _clear_targets(targets: list[Path], runtime: Path) -> dict[str, int]:
    """Remove approved targets while preserving logs and job history."""
    removed_files = 0
    removed_bytes = 0
    for path in targets:
        count, size = _remove_path(path, runtime)
        removed_files += count
        removed_bytes += size
    return {"removed_files": removed_files, "removed_bytes": removed_bytes}


def clear_raw_data() -> dict[str, Any]:
    """Remove Raw databases and Raw generator publications only."""
    runtime = get_runtime_home().resolve()
    result = _clear_targets(_raw_clear_targets(runtime), runtime)
    return {"message": "Raw data cleared", **result}


def clear_all_data() -> dict[str, Any]:
    """Remove generated, medallion, serving, and ML data."""
    runtime = get_runtime_home().resolve()
    result = _clear_targets(_all_clear_targets(runtime), runtime)
    return {"message": "All generated data cleared", **result}


def _apply_noise_profile(config: dict[str, Any], profile: str) -> None:
    """Scale named Raw-data noise without changing allowed rules."""
    noise = config["noise"]
    if profile == "low":
        factor = 0.35
    elif profile == "stress":
        factor = 2.0
    else:
        factor = 1.0
    for key in (
        "duplicate_execution_probability",
        "missing_execution_probability",
        "null_measurement_probability",
        "outlier_probability",
    ):
        noise[key] = min(float(noise[key]) * factor, 0.05)


def default_options() -> GeneratorOptions:
    """Build UI defaults from the tracked generator configuration."""
    generation = load_app_config("data_operations.generator")["data_generation"]
    reverse_profiles = {value: key for key, value in PROFILE_KEYS.items()}
    return GeneratorOptions(
        profile=reverse_profiles[generation["volume"]],
        random_seed=generation["random_seed"],
        actual_start=date.fromisoformat(generation["start_date_actual"]),
        actual_end=date.fromisoformat(generation["end_date_actual"]),
        forecast_start=date.fromisoformat(generation["start_date_forecast"]),
        forecast_end=date.fromisoformat(generation["end_date_forecast"]),
        plan_as_of_dates=[date.fromisoformat(value) for value in generation["plan_as_of_dates"]],
        noise_profile=generation["noise_profile"],
    )
