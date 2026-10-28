"""Stage and atomically publish one complete ML run outside the repository."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from capacity_twin_core.runtime.database_paths import (
    get_active_run_pointer,
    get_release_pointer,
    get_runtime_home,
)
from decision_intelligence.ml_support import (
    file_sha256,
    set_active_paths,
)


@dataclass(frozen=True)
class PublicationCandidate:
    """Paths belonging to one unpublished candidate run."""

    run_id: str
    root: Path
    database: Path
    models: Path
    source_sha256: str
    input_paths: dict[str, Path]
    input_checksums: dict[str, str]
    pipeline_run_id: str
    source_run_id: str
    previous_results: dict


def _captured_inputs(runtime: Path) -> tuple[dict[str, Path], str, str]:
    pointer = json.loads(
        get_active_run_pointer(runtime).read_text(encoding="utf-8")
    )
    pipeline_run_id = pointer["active_run_id"]
    pipeline_manifest_path = Path(pointer["manifest"])
    if not pipeline_manifest_path.is_absolute():
        pipeline_manifest_path = runtime / pipeline_manifest_path
    pipeline_manifest = json.loads(pipeline_manifest_path.read_text(encoding="utf-8"))
    source_manifest_path = Path(pipeline_manifest["source_bundle_manifest"])
    if not source_manifest_path.is_absolute():
        source_manifest_path = runtime / source_manifest_path
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))

    inputs = {
        "serving": runtime / "artifacts" / pipeline_run_id / "serving.duckdb"
    }
    for role in ("reference", "mapping"):
        details = next(
            item
            for item in source_manifest["files"].values()
            if item["role"] == role
        )
        path = Path(details["path"])
        inputs[role] = path if path.is_absolute() else runtime / path
    for name, path in inputs.items():
        resolved = path.resolve()
        if runtime.resolve() not in resolved.parents or not resolved.is_file():
            raise ValueError(f"Pinned {name} input is outside runtime or missing")
        inputs[name] = resolved
    return inputs, pipeline_run_id, pipeline_manifest["source_bundle_run_id"]


def create_candidate(*, preserve_existing: bool = False) -> PublicationCandidate:
    """Create an output-only ML candidate over checksum-pinned attached inputs."""
    runtime = get_runtime_home()
    inputs, pipeline_run_id, source_run_id = _captured_inputs(runtime)
    input_checksums = {
        name: file_sha256(path) for name, path in inputs.items()
    }
    source_sha256 = input_checksums["serving"]
    current_database: Path | None = None
    current_models: Path | None = None
    previous_results: dict = {}
    if preserve_existing:
        pointer_path = runtime / "ml_current.json"
        if not pointer_path.is_file():
            raise ValueError("A complete ML publication is required for a selected workflow run")
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        current_database = (runtime / pointer["database"]).resolve()
        current_manifest = (runtime / pointer["manifest"]).resolve()
        current_models = (runtime / pointer["models"]).resolve()
        for path in (current_database, current_manifest, current_models):
            if runtime.resolve() not in path.parents:
                raise ValueError("ML publication pointer escapes the runtime home")
        manifest = json.loads(current_manifest.read_text(encoding="utf-8"))
        if manifest.get("input_checksums", {}).get(
            "serving", manifest.get("source_database_sha256")
        ) != source_sha256:
            raise ValueError("Serving data is newer than ML outputs; run all workflows")
        previous_results = {
            int(priority): result
            for priority, result in manifest.get("workflow_results", {}).items()
        }

    run_id = f"ml-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    root = runtime / ".staging" / run_id
    root.mkdir(parents=True, exist_ok=False)
    database = root / "ml.duckdb"
    models = root / "models"
    try:
        if preserve_existing:
            assert current_database is not None
            assert current_models is not None
            shutil.copy2(current_database, database)
            shutil.copytree(current_models, models)
        else:
            with duckdb.connect(str(database)):
                pass
            models.mkdir()
        set_active_paths(database, models, input_paths=inputs)
    except Exception:
        set_active_paths(None, None)
        shutil.rmtree(root, ignore_errors=True)
        raise
    return PublicationCandidate(
        run_id,
        root,
        database,
        models,
        source_sha256,
        inputs,
        input_checksums,
        pipeline_run_id,
        source_run_id,
        previous_results,
    )


def _output_schema(database: Path) -> dict[str, list[dict[str, str]]]:
    """Capture table feature/output schemas for compatibility checks."""
    conn = duckdb.connect(str(database), read_only=True)
    try:
        tables = conn.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'main'
              AND (table_name LIKE 'ml_%' OR table_name = 'ml_model_registry')
            ORDER BY table_name
            """
        ).fetchall()
        return {
            table_name: [
                {"name": row[0], "type": row[1]}
                for row in conn.execute(f'DESCRIBE "{table_name}"').fetchall()
            ]
            for (table_name,) in tables
        }
    finally:
        conn.close()


def publish_candidate(
    candidate: PublicationCandidate,
    results: dict,
) -> Path:
    """Validate checksums and atomically replace the promoted ML artifacts."""
    if not candidate.database.is_file():
        raise ValueError("Candidate ML database is missing")
    failures = [value for value in results.values() if value.get("status") != "OK"]
    if failures:
        raise ValueError("Cannot publish a candidate containing failed workflows")
    runtime = get_runtime_home()

    with duckdb.connect(str(candidate.database)) as connection:
        connection.execute("DROP TABLE IF EXISTS ml_model_registry")
        registry_rows = [
            (
                int(priority),
                str(result.get("workflow", f"workflow-{priority}")),
                str(result["status"]),
                candidate.run_id,
                candidate.pipeline_run_id,
                candidate.input_checksums["serving"],
            )
            for priority, result in sorted(results.items())
        ]
        connection.execute(
            """
            CREATE TABLE ml_model_registry (
                workflow_priority INTEGER,
                workflow_name VARCHAR,
                status VARCHAR,
                ml_run_id VARCHAR,
                input_pipeline_run_id VARCHAR,
                input_serving_sha256 VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO ml_model_registry VALUES (?, ?, ?, ?, ?, ?)",
            registry_rows,
        )
        invalid = connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_catalog = current_database()
              AND table_type = 'BASE TABLE'
              AND table_name <> 'ml_model_registry'
              AND table_name NOT LIKE 'ml_%'
            """
        ).fetchall()
        if invalid:
            raise ValueError(f"ML publication ownership violation: {invalid}")

    manifest = {
        "schema_version": 1,
        "run_id": candidate.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "database_sha256": file_sha256(candidate.database),
        "source_database_sha256": candidate.source_sha256,
        "input_pipeline_run_id": candidate.pipeline_run_id,
        "input_source_run_id": candidate.source_run_id,
        "input_checksums": candidate.input_checksums,
        "input_paths": {
            name: str(path.relative_to(runtime))
            for name, path in candidate.input_paths.items()
        },
        "output_schema": _output_schema(candidate.database),
        "workflow_results": results,
    }
    manifest_path = candidate.root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )

    artifacts = runtime / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    final_root = artifacts / candidate.run_id
    if final_root.exists():
        raise FileExistsError(f"ML run already exists: {final_root}")

    # A versioned directory becomes immutable before the tiny pointer changes.
    set_active_paths(None, None)
    os.replace(candidate.root, final_root)
    relative_root = final_root.relative_to(runtime)
    pointer = {
        "schema_version": 1,
        "run_id": candidate.run_id,
        "database": str(relative_root / candidate.database.name),
        "models": str(relative_root / candidate.models.name),
        "manifest": str(relative_root / manifest_path.name),
        "database_sha256": manifest["database_sha256"],
    }
    pointer_path = runtime / "ml_current.json"
    fd, temp_name = tempfile.mkstemp(dir=runtime, suffix=".pointer.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(pointer, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, pointer_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    _promote_compatible_release(runtime, candidate, pointer, manifest)
    return final_root / candidate.database.name


def _promote_compatible_release(
    runtime: Path,
    candidate: PublicationCandidate,
    ml_pointer: dict,
    ml_manifest: dict,
) -> None:
    """Atomically select source, medallion, Serving, and ML as one release."""
    active = json.loads(
        get_active_run_pointer(runtime).read_text(encoding="utf-8")
    )
    if active.get("active_run_id") != candidate.pipeline_run_id:
        raise ValueError("Pipeline candidate changed while ML was building")
    pipeline_manifest_path = Path(active["manifest"])
    if not pipeline_manifest_path.is_absolute():
        pipeline_manifest_path = runtime / pipeline_manifest_path
    pipeline_manifest = json.loads(pipeline_manifest_path.read_text(encoding="utf-8"))
    serving = pipeline_manifest["files"]["serving.duckdb"]
    if serving["sha256"] != candidate.input_checksums["serving"]:
        raise ValueError("ML input checksum does not match the pipeline candidate")
    previous: dict = {}
    release_pointer = get_release_pointer(runtime)
    if release_pointer.is_file():
        previous = json.loads(release_pointer.read_text(encoding="utf-8"))
    publications = {
        layer: {
            "run_id": candidate.pipeline_run_id,
            "path": str(runtime / "artifacts" / candidate.pipeline_run_id / f"{layer}.duckdb"),
            "sha256": pipeline_manifest["files"][f"{layer}.duckdb"]["sha256"],
            "schema_version": "phase-3b-1.0",
        }
        for layer in ("bronze", "silver", "gold", "serving")
    }
    _atomic_release = {
        "release_id": f"{candidate.pipeline_run_id}+{candidate.run_id}",
        "previous_release_id": previous.get("release_id"),
        "previous_release": previous or None,
        "promoted_at": datetime.now(UTC).isoformat(),
        "compatibility_version": "release-2.0",
        "source_bundle": {
            "run_id": candidate.source_run_id,
            "checksum": pipeline_manifest["source_bundle_checksum"],
            "manifest": pipeline_manifest["source_bundle_manifest"],
        },
        "publications": publications,
        "ml": {
            "run_id": candidate.run_id,
            "path": ml_pointer["database"],
            "sha256": ml_manifest["database_sha256"],
            "manifest": ml_pointer["manifest"],
            "input_pipeline_run_id": candidate.pipeline_run_id,
            "input_checksums": candidate.input_checksums,
            "schema_version": "ml-2.0",
        },
    }
    fd, temp_name = tempfile.mkstemp(dir=runtime, suffix=".release.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(_atomic_release, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, release_pointer)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    active["release_pending_ml"] = False
    active["compatible_ml_run_id"] = candidate.run_id
    fd, temp_name = tempfile.mkstemp(dir=runtime, suffix=".current.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(active, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, get_active_run_pointer(runtime))
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def discard_candidate(candidate: PublicationCandidate) -> None:
    """Discard a failed candidate without touching promoted artifacts."""
    set_active_paths(None, None, input_paths=None)
    shutil.rmtree(candidate.root, ignore_errors=True)
