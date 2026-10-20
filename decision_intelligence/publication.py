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

from capacity_twin_core.runtime.database_paths import get_runtime_home
from decision_intelligence.ml_support import (
    file_sha256,
    set_active_paths,
    source_database_path,
)


@dataclass(frozen=True)
class PublicationCandidate:
    """Paths belonging to one unpublished candidate run."""

    run_id: str
    root: Path
    database: Path
    models: Path
    source_sha256: str
    previous_results: dict


def create_candidate(*, preserve_existing: bool = False) -> PublicationCandidate:
    """Copy validated inputs into an isolated candidate database."""
    source = source_database_path()
    if not source.is_file():
        raise FileNotFoundError(f"ML source database not found: {source}")
    runtime = get_runtime_home()
    source_sha256 = file_sha256(source)
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
        if manifest.get("source_database_sha256") != source_sha256:
            raise ValueError("Gold data is newer than ML outputs; run all workflows")
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
            shutil.copy2(source, database)
            models.mkdir()
        set_active_paths(database, models)
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
        previous_results,
    )


def _output_schema(database: Path) -> dict[str, list[dict[str, str]]]:
    """Capture table feature/output schemas for compatibility checks."""
    conn = duckdb.connect(str(database), read_only=True)
    try:
        tables = conn.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name LIKE 'gold_%'
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

    manifest = {
        "schema_version": 1,
        "run_id": candidate.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "database_sha256": file_sha256(candidate.database),
        "source_database_sha256": candidate.source_sha256,
        "output_schema": _output_schema(candidate.database),
        "workflow_results": results,
    }
    manifest_path = candidate.root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )

    runtime = get_runtime_home()
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
    return final_root / candidate.database.name


def discard_candidate(candidate: PublicationCandidate) -> None:
    """Discard a failed candidate without touching promoted artifacts."""
    set_active_paths(None, None)
    shutil.rmtree(candidate.root, ignore_errors=True)
