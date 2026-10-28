"""Stage a complete Raw candidate and publish validated files atomically."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from capacity_twin_core.runtime.database_paths import get_source_bundle_pointer
from data_operations.generator.catalogs.contract_tables import CATALOG_VERSION
from data_operations.generator.rules.determinism import stable_id

RAW_SCHEMA_VERSION = "raw-source-2.0"
BUNDLE_SCHEMA_VERSION = "source-bundle-2.0"


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Replace a small JSON pointer without exposing a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def create_candidate(config: dict[str, Any]) -> tuple[str, Path]:
    """Create one run-scoped candidate for all source files."""
    run_id = stable_id(
        "generator-run",
        config["data_generation"]["random_seed"],
        config["data_generation"]["volume"],
        datetime.now(UTC).isoformat(),
    )
    runtime_home = Path(config["paths"]["runtime_home"])
    candidate = runtime_home / "source_bundles" / run_id
    (candidate / "raw").mkdir(parents=True, exist_ok=False)
    return run_id, candidate


def initialize_raw_databases(raw_dir: Path, config: dict[str, Any]) -> None:
    """Create exactly the seven configured Raw source files before generation."""
    names = list(config["databases"]["raw"].values())
    if len(names) != 7 or len(set(names)) != 7:
        raise ValueError("Source bundle requires exactly seven unique Raw databases")
    for filename in names:
        with sqlite3.connect(raw_dir / filename):
            pass


def add_source_metadata(
    raw_dir: Path,
    config: dict[str, Any],
    *,
    source_run_id: str,
    extracted_at_utc: str,
) -> None:
    """Add source identity and extraction lineage to every generated Raw row."""
    company_id = str(config.get("brand", {}).get("primary_company", "UNKNOWN"))
    for source_system_id, filename in config["databases"]["raw"].items():
        with sqlite3.connect(raw_dir / filename) as connection:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            for table in tables:
                columns = {
                    row[1]
                    for row in connection.execute(f'PRAGMA table_info("{table}")')
                }
                site_column = (
                    "site_code"
                    if "site_code" in columns
                    else ("site" if "site" in columns else None)
                )
                additions = {
                    "source_system_id": source_system_id,
                    "source_company_id": company_id,
                    "source_site_id": None,
                    "source_record_id": None,
                    "source_batch_id": source_run_id,
                    "extracted_at_utc": extracted_at_utc,
                }
                for column in additions:
                    if column not in columns:
                        connection.execute(
                            f'ALTER TABLE "{table}" ADD COLUMN "{column}" TEXT'
                        )
                site_expression = f'CAST("{site_column}" AS TEXT)' if site_column else "NULL"
                connection.execute(
                    f"""
                    UPDATE "{table}"
                    SET source_system_id = ?,
                        source_company_id = ?,
                        source_site_id = {site_expression},
                        source_record_id = ? || ':' || CAST(rowid AS TEXT),
                        source_batch_id = ?,
                        extracted_at_utc = ?
                    """,
                    (
                        source_system_id,
                        company_id,
                        table,
                        source_run_id,
                        extracted_at_utc,
                    ),
                )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sqlite_tables(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            table: int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            for table in tables
        }


def _duckdb_tables(path: Path) -> dict[str, int]:
    with duckdb.connect(str(path), read_only=True) as connection:
        objects = connection.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name
            """
        ).fetchall()
        return {
            f"{schema}.{table}": int(
                connection.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"').fetchone()[0]
            )
            for schema, table in objects
        }


def publish_candidate(
    run_id: str,
    candidate_dir: Path,
    config: dict[str, Any],
    validation_report: dict[str, Any],
    preflight_report: dict[str, Any],
    catalog_report: dict[str, Any],
) -> Path:
    """Seal all nine source files and atomically select the bundle."""
    runtime_home = Path(config["paths"]["runtime_home"]).resolve()
    raw_dir = candidate_dir / "raw"
    file_details: dict[str, dict[str, Any]] = {}
    for filename in config["databases"]["raw"].values():
        path = raw_dir / filename
        tables = _sqlite_tables(path)
        file_details[filename] = {
            "role": "raw",
            "path": path.relative_to(runtime_home).as_posix(),
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
            "schema_version": RAW_SCHEMA_VERSION,
            "table_count": len(tables),
            "tables": tables,
        }
    for role, filename in config["databases"]["source_bundle"].items():
        path = candidate_dir / filename
        tables = _duckdb_tables(path)
        file_details[filename] = {
            "role": role,
            "path": path.relative_to(runtime_home).as_posix(),
            "sha256": _sha256(path),
            "size_bytes": path.stat().st_size,
            "schema_version": catalog_report["schema_versions"][role],
            "table_count": len(tables),
            "tables": tables,
        }
    if len(file_details) != 9:
        raise ValueError("A source bundle must contain seven Raw files and two DuckDB files")
    checksum_payload = json.dumps(
        file_details, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    bundle_checksum = hashlib.sha256(checksum_payload).hexdigest()
    generated_at = catalog_report["published_at"]
    manifest = {
        "manifest_version": 1,
        "source_run_id": run_id,
        "run_id": run_id,
        "shared_run_id": run_id,
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "schema_versions": {
            "bundle": BUNDLE_SCHEMA_VERSION,
            "raw": RAW_SCHEMA_VERSION,
            **catalog_report["schema_versions"],
        },
        "catalog_version": CATALOG_VERSION,
        "generated_at_utc": generated_at,
        "bundle_checksum": bundle_checksum,
        "seed": config["data_generation"]["random_seed"],
        "volume": config["data_generation"]["volume"],
        "date_contract": {
            key: config["data_generation"][key]
            for key in (
                "start_date_actual",
                "end_date_actual",
                "start_date_forecast",
                "end_date_forecast",
                "plan_as_of_dates",
            )
        },
        "preflight": preflight_report,
        "validation": validation_report,
        "files": file_details,
        "promotion_state": "published",
    }
    manifest_path = candidate_dir / "source_bundle_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    _atomic_json(
        get_source_bundle_pointer(runtime_home),
        {
            "pointer_version": 1,
            "source_run_id": run_id,
            "run_id": run_id,
            "shared_run_id": run_id,
            "generated_at_utc": generated_at,
            "bundle_checksum": bundle_checksum,
            "manifest": manifest_path.relative_to(runtime_home).as_posix(),
            "raw_directory": raw_dir.relative_to(runtime_home).as_posix(),
            "reference_database": file_details[
                config["databases"]["source_bundle"]["reference"]
            ]["path"],
            "mapping_database": file_details[
                config["databases"]["source_bundle"]["mapping"]
            ]["path"],
            "schema_versions": manifest["schema_versions"],
        },
    )
    return manifest_path
