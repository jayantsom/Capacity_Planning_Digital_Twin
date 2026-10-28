"""Runtime paths, app configuration, and database connection helpers."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

import duckdb
import yaml

from capacity_twin_core.logging import logger

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CORE_CONFIG_PATH = PROJECT_ROOT / "src" / "capacity_twin_core" / "config.yaml"
APP_CONFIG_PATHS = (
    CORE_CONFIG_PATH,
    PROJECT_ROOT / "data_operations" / "generator" / "config.yaml",
    PROJECT_ROOT / "data_operations" / "pipeline" / "config.yaml",
)


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge nested app configuration without sharing mutable values."""
    merged = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def get_runtime_home() -> Path:
    """Resolve the external runtime directory used for generated artifacts."""
    runtime_config = load_app_config("capacity_twin_core")["runtime"]
    configured = os.environ.get(runtime_config["home_env"])
    if configured:
        return Path(configured).expanduser().resolve()

    windows_default = os.path.expandvars(runtime_config["windows_default"])
    if "%" not in windows_default:
        return Path(windows_default).expanduser().resolve()
    return (Path.home() / ".capacity_planning_digital_twin").resolve()


def get_active_run_pointer(runtime_home: Path | None = None) -> Path:
    """Return the configured promoted-run pointer path."""
    pointer_name = load_app_config("capacity_twin_core")["runtime"]["active_run_pointer"]
    return (runtime_home or get_runtime_home()) / pointer_name


def get_release_pointer(runtime_home: Path | None = None) -> Path:
    """Return the top-level compatible publication pointer."""
    pointer_name = load_app_config("capacity_twin_core")["runtime"]["release_pointer"]
    return (runtime_home or get_runtime_home()) / pointer_name


def get_raw_run_pointer(runtime_home: Path | None = None) -> Path:
    """Compatibility alias for the unified source-bundle pointer."""
    return get_source_bundle_pointer(runtime_home)


def get_control_run_pointer(runtime_home: Path | None = None) -> Path:
    """Compatibility alias for the unified source-bundle pointer."""
    return get_source_bundle_pointer(runtime_home)


def get_source_bundle_pointer(runtime_home: Path | None = None) -> Path:
    """Return the only mutable pointer for immutable source publications."""
    pointer_name = load_app_config("capacity_twin_core")["runtime"][
        "source_bundle_pointer"
    ]
    return (runtime_home or get_runtime_home()) / pointer_name


def capture_source_bundle(runtime_home: Path | None = None) -> dict[str, Any]:
    """Capture and validate the current immutable source-bundle paths once."""
    runtime = (runtime_home or get_runtime_home()).resolve()
    pointer_path = get_source_bundle_pointer(runtime)
    if not pointer_path.is_file():
        raise FileNotFoundError("No published source bundle")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    manifest_path = Path(pointer["manifest"])
    if not manifest_path.is_absolute():
        manifest_path = runtime / manifest_path
    manifest_path = manifest_path.resolve()
    if runtime != manifest_path and runtime not in manifest_path.parents:
        raise ValueError("Source bundle manifest escapes the runtime home")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source_run_id") != pointer.get("source_run_id"):
        raise ValueError("Source bundle pointer and manifest run IDs differ")
    if manifest.get("bundle_checksum") != pointer.get("bundle_checksum"):
        raise ValueError("Source bundle pointer and manifest checksums differ")
    canonical = json.dumps(
        manifest.get("files", {}), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != manifest.get("bundle_checksum"):
        raise ValueError("Source bundle canonical checksum failed")

    files: dict[str, Path] = {}
    for name, details in manifest.get("files", {}).items():
        path = Path(details["path"])
        if not path.is_absolute():
            path = runtime / path
        path = path.resolve()
        if runtime != path and runtime not in path.parents:
            raise ValueError(f"Source bundle file escapes runtime home: {name}")
        if not path.is_file():
            raise FileNotFoundError(f"Source bundle file is missing: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != details.get("sha256"):
            raise ValueError(f"Source bundle checksum failed: {name}")
        files[name] = path
    return {
        **pointer,
        "manifest_path": manifest_path,
        "manifest_data": manifest,
        "files": files,
    }


def load_app_config(app_name: str) -> dict[str, Any]:
    """Load one root app, an app module, or the shared core configuration."""
    config_path = (
        CORE_CONFIG_PATH
        if app_name == "capacity_twin_core"
        else PROJECT_ROOT.joinpath(*app_name.split(".")) / "config.yaml"
    )
    if not config_path.is_file():
        raise FileNotFoundError(f"App configuration not found: {config_path}")
    with config_path.open(encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Return the merged shared, generator, and pipeline configuration."""
    if config_path is not None:
        explicit_path = Path(config_path)
        if not explicit_path.is_absolute():
            explicit_path = PROJECT_ROOT / explicit_path
        with explicit_path.open(encoding="utf-8") as file:
            return yaml.safe_load(file) or {}

    config: dict[str, Any] = {}
    for app_config_path in APP_CONFIG_PATHS:
        with app_config_path.open(encoding="utf-8") as file:
            config = _deep_merge(config, yaml.safe_load(file) or {})

    runtime_home = get_runtime_home()
    config["paths"] = {
        "runtime_home": str(runtime_home),
        "data_root": str(runtime_home),
        "raw_sqlite": str(runtime_home / "raw" / "sqlite"),
        "bronze": str(runtime_home / "bronze"),
        "silver": str(runtime_home / "silver"),
        "gold": str(runtime_home / "gold"),
        "serving": str(runtime_home / "serving"),
        "control": str(runtime_home / "control"),
        "logs": str(runtime_home / "logs"),
        "models": str(runtime_home / "models"),
    }
    return config


def get_sqlite_path(db_name: str, config: dict[str, Any]) -> Path:
    """Resolve one generated Raw SQLite database path."""
    raw_dir = Path(config["paths"]["raw_sqlite"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir / db_name


@contextmanager
def sqlite_connection(db_path: Path, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Open SQLite with guaranteed close and optional read-only access."""
    uri = f"{db_path.resolve().as_uri()}?mode=ro" if read_only else str(db_path)
    conn = sqlite3.connect(uri, uri=read_only)
    conn.row_factory = sqlite3.Row
    try:
        logger.debug(f"SQLite connection opened: {db_path}")
        yield conn
        if not read_only:
            conn.commit()
    except Exception as error:
        if not read_only:
            conn.rollback()
        logger.error(f"SQLite error on {db_path}: {error}")
        raise
    finally:
        conn.close()
        logger.debug(f"SQLite connection closed: {db_path}")


def get_duckdb_connection(
    config: dict[str, Any],
    *,
    database_key: str,
    read_only: bool = False,
) -> duckdb.DuckDBPyConnection:
    """Open a configured DuckDB database."""
    db_path = Path(config["paths"]["data_root"]) / config["databases"][database_key]
    if not read_only:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"DuckDB connection: {db_path}")
    return duckdb.connect(str(db_path), read_only=read_only)