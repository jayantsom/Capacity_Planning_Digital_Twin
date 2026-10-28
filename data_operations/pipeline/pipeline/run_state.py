"""Candidate-run manifests, validation, promotion, retry, and rollback."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from capacity_twin_core.runtime.database_paths import (
    capture_source_bundle,
    get_active_run_pointer,
    get_release_pointer,
    get_source_bundle_pointer,
)

DATABASE_FILES = ("bronze.duckdb", "silver.duckdb", "gold.duckdb", "serving.duckdb")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Replace a small JSON file without exposing a partially written value."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _config_hash(config: dict[str, Any]) -> str:
    """Hash semantic settings while excluding machine-specific resolved paths."""
    semantic_config = {key: value for key, value in config.items() if key != "paths"}
    payload = json.dumps(semantic_config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_checksum(path: Path) -> str:
    """Return a streaming SHA-256 checksum for one artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class RunPaths:
    """Physical paths owned by one immutable candidate run."""

    runtime_home: Path
    run_id: str

    @property
    def run_dir(self) -> Path:
        return self.runtime_home / "artifacts" / self.run_id

    @property
    def manifest(self) -> Path:
        return self.run_dir / "manifest.json"

    @property
    def pointer(self) -> Path:
        return get_active_run_pointer(self.runtime_home)

    def database(self, layer: str, *, staging: bool = False) -> Path:
        suffix = ".staging" if staging else ""
        return self.run_dir / f"{layer}.duckdb{suffix}"


class PipelineRun:
    """Manage one candidate from creation through atomic pointer promotion."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        run_id: str | None = None,
        retry_of: str | None = None,
    ) -> None:
        runtime_home = Path(config["paths"]["runtime_home"]).resolve()
        self.paths = RunPaths(runtime_home, run_id or _new_run_id())
        self.paths.run_dir.mkdir(parents=True, exist_ok=False)
        current = self.read_pointer(runtime_home)
        source = capture_source_bundle(runtime_home)
        source_manifest = source["manifest_data"]
        source_run_id = source["source_run_id"]
        source_checksum = source["bundle_checksum"]
        raw_paths = [
            path
            for name, path in source["files"].items()
            if source_manifest["files"][name]["role"] == "raw"
        ]
        self.source_raw_directory = raw_paths[0].parent
        self.source_reference_database = source["files"]["reference.duckdb"]
        self.source_mapping_database = source["files"]["mapping.duckdb"]
        self.source_bundle_checksum = source_checksum
        self.source_run_id = source_run_id
        self.manifest: dict[str, Any] = {
            "manifest_version": 1,
            "run_id": self.paths.run_id,
            "parent_run_id": current.get("active_run_id"),
            "retry_of_run_id": retry_of,
            "source_bundle_run_id": source_run_id,
            "source_bundle_checksum": source_checksum,
            "source_bundle_manifest": str(source["manifest_path"]),
            "source_raw_run_id": source_run_id,
            "source_control_run_id": source_run_id,
            "source_control_sha256": source_checksum,
            "control_catalog_version": source_manifest.get("catalog_version"),
            "config_hash": _config_hash(config),
            "created_at": _utc_now(),
            "completed_at": None,
            "promoted_at": None,
            "status": "BUILDING",
            "promotion_state": "CANDIDATE",
            "active": False,
            "stages": {},
            "source_counts": {},
            "files": {},
            "validations": [],
        }
        self._write_manifest()

    @staticmethod
    def read_pointer(runtime_home: Path) -> dict[str, Any]:
        pointer = get_active_run_pointer(runtime_home)
        if not pointer.is_file():
            return {}
        return json.loads(pointer.read_text(encoding="utf-8"))

    @staticmethod
    def read_raw_pointer(runtime_home: Path) -> dict[str, Any]:
        """Compatibility reader for the unified source publication."""
        pointer = get_source_bundle_pointer(runtime_home)
        if not pointer.is_file():
            return {}
        return json.loads(pointer.read_text(encoding="utf-8"))

    @staticmethod
    def read_control_pointer(runtime_home: Path) -> dict[str, Any]:
        """Compatibility reader for the unified source publication."""
        pointer = get_source_bundle_pointer(runtime_home)
        if not pointer.is_file():
            return {}
        return json.loads(pointer.read_text(encoding="utf-8"))

    def begin_stage(self, stage: str) -> float:
        """Record that a stage started and return its monotonic timer."""
        self.manifest["stages"][stage] = {
            "status": "RUNNING",
            "started_at": _utc_now(),
        }
        self._write_manifest()
        return time.perf_counter()

    def complete_stage(
        self,
        stage: str,
        started: float,
        *,
        counts: dict[str, int] | None = None,
    ) -> None:
        """Record a successfully validated stage."""
        stage_data = self.manifest["stages"][stage]
        stage_data.update(
            {
                "status": "PASSED",
                "completed_at": _utc_now(),
                "duration_seconds": round(time.perf_counter() - started, 3),
                "counts": counts or {},
            }
        )
        if stage == "bronze":
            self.manifest["source_counts"] = counts or {}
        self._write_manifest()

    def fail(self, stage: str, error: Exception) -> None:
        """Mark a candidate failed without changing the active pointer."""
        stage_data = self.manifest["stages"].setdefault(stage, {})
        stage_data.update(
            {
                "status": "FAILED",
                "completed_at": _utc_now(),
                "error": f"{type(error).__name__}: {error}",
            }
        )
        self.manifest.update({"status": "FAILED", "completed_at": _utc_now(), "active": False})
        self._write_manifest()

    def validate_database(self, layer: str, required_objects: list[str]) -> dict[str, int]:
        """Check a staged database, record row counts, then seal its filename."""
        staging = self.paths.database(layer, staging=True)
        if not staging.is_file():
            raise FileNotFoundError(f"Missing staged {layer} database: {staging}")

        counts: dict[str, int] = {}
        with duckdb.connect(str(staging), read_only=True) as connection:
            objects = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_catalog = current_database()
                    """
                ).fetchall()
            }
            missing = sorted(set(required_objects) - objects)
            if missing:
                raise ValueError(f"{layer} is missing required objects: {missing}")
            for name in required_objects:
                counts[name] = connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]

        final = self.paths.database(layer)
        os.replace(staging, final)
        self.manifest["files"][final.name] = {
            "sha256": file_checksum(final),
            "size_bytes": final.stat().st_size,
            "objects": counts,
        }
        self.manifest["validations"].append(
            {
                "name": f"{layer}_required_objects",
                "status": "PASSED",
                "checked_at": _utc_now(),
            }
        )
        self._write_manifest()
        return counts

    def promote(self) -> None:
        """Atomically point readers at a complete, validated artifact set."""
        source_pointer = self.read_raw_pointer(self.paths.runtime_home)
        if (
            source_pointer.get("source_run_id") != self.source_run_id
            or source_pointer.get("bundle_checksum") != self.source_bundle_checksum
        ):
            raise ValueError("Source bundle changed while the pipeline was building")
        missing = [name for name in DATABASE_FILES if not (self.paths.run_dir / name).is_file()]
        if missing:
            raise ValueError(f"Cannot promote incomplete run; missing {missing}")
        failed = [item for item in self.manifest["validations"] if item["status"] != "PASSED"]
        if failed:
            raise ValueError("Cannot promote a run with failed validations")

        current = self.read_pointer(self.paths.runtime_home)
        previous = current.get("active_run_id")
        promoted_at = _utc_now()
        if previous:
            previous_manifest_path = (
                self.paths.runtime_home / "artifacts" / previous / "manifest.json"
            )
            if previous_manifest_path.is_file():
                previous_manifest = json.loads(previous_manifest_path.read_text(encoding="utf-8"))
                previous_manifest.update(
                    {"active": False, "promotion_state": "PREVIOUS_KNOWN_GOOD"}
                )
                _atomic_json(previous_manifest_path, previous_manifest)
        pointer = {
            "active_run_id": self.paths.run_id,
            "previous_run_id": previous,
            "promoted_at": promoted_at,
            "manifest": str(self.paths.manifest),
            "serving_database": str(self.paths.database("serving")),
            "source_raw_run_id": self.manifest["source_raw_run_id"],
            "source_control_run_id": self.manifest["source_control_run_id"],
            "source_control_sha256": self.manifest["source_control_sha256"],
            "release_pending_ml": True,
        }
        _atomic_json(self.paths.pointer, pointer)
        # current.json remains a compatibility pointer for pipeline and ML staging.
        # release_current.json is intentionally not changed here.  The ML publisher
        # performs the one atomic release switch after compatible ML is available.
        self.manifest.update(
            {
                "status": "PROMOTED",
                "promotion_state": "ACTIVE",
                "active": True,
                "promoted_at": promoted_at,
                "completed_at": promoted_at,
            }
        )
        self._write_manifest()

    def _write_manifest(self) -> None:
        _atomic_json(self.paths.manifest, self.manifest)


def _new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def rollback(runtime_home: Path) -> str:
    """Swap the active pointer with the previous validated run."""
    runtime_home = runtime_home.resolve()
    pointer = PipelineRun.read_pointer(runtime_home)
    active = pointer.get("active_run_id")
    previous = pointer.get("previous_run_id")
    if not active or not previous:
        raise ValueError("No previous promoted run is available for rollback")

    previous_dir = runtime_home / "artifacts" / previous
    manifest_path = previous_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Previous run manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") not in {"PROMOTED", "ROLLED_BACK"}:
        raise ValueError(f"Previous run {previous} is not a known-good run")
    for name in DATABASE_FILES:
        path = previous_dir / name
        expected = manifest.get("files", {}).get(name, {}).get("sha256")
        if not path.is_file() or not expected or file_checksum(path) != expected:
            raise ValueError(f"Previous artifact failed checksum validation: {name}")

    rolled_at = _utc_now()
    _atomic_json(
        get_active_run_pointer(runtime_home),
        {
            "active_run_id": previous,
            "previous_run_id": active,
            "promoted_at": rolled_at,
            "manifest": str(manifest_path),
            "serving_database": str(previous_dir / "serving.duckdb"),
            "source_raw_run_id": manifest.get("source_raw_run_id"),
            "source_control_run_id": manifest.get("source_control_run_id"),
            "source_control_sha256": manifest.get("source_control_sha256"),
            "rollback_from_run_id": active,
        },
    )
    release_pointer = get_release_pointer(runtime_home)
    if release_pointer.is_file():
        current_release = json.loads(release_pointer.read_text(encoding="utf-8"))
        previous_release = current_release.get("previous_release")
        if (
            previous_release
            and previous_release.get("publications", {})
            .get("serving", {})
            .get("run_id")
            == previous
            and previous_release.get("ml")
        ):
            restored_release = {
                **previous_release,
                "previous_release_id": current_release.get("release_id"),
                "previous_release": current_release,
                "promoted_at": rolled_at,
                "rollback_from_release_id": current_release.get("release_id"),
            }
            _atomic_json(release_pointer, restored_release)
    active_manifest_path = runtime_home / "artifacts" / active / "manifest.json"
    if active_manifest_path.is_file():
        active_manifest = json.loads(active_manifest_path.read_text(encoding="utf-8"))
        active_manifest.update({"active": False, "promotion_state": "ROLLBACK_TARGET"})
        _atomic_json(active_manifest_path, active_manifest)
    manifest.update(
        {
            "status": "ROLLED_BACK",
            "promotion_state": "ACTIVE_AFTER_ROLLBACK",
            "active": True,
            "promoted_at": rolled_at,
        }
    )
    _atomic_json(manifest_path, manifest)
    return previous
