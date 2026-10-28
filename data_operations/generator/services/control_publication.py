"""Build and atomically publish the application-owned control catalog."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_operations.generator.catalogs.contract_tables import CATALOG_VERSION
from data_operations.generator.services.mapping_publication import (
    MAPPING_SCHEMA_VERSION,
    build_mapping_database,
)
from data_operations.generator.services.reference_publication import (
    REFERENCE_SCHEMA_VERSION,
    build_reference_database,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def publish_source_catalogs(
    config: dict[str, Any],
    bundle_dir: Path,
    source_run_id: str,
    *,
    published_at: str | None = None,
) -> dict[str, Any]:
    """Build Reference and Mapping inside one source-bundle candidate."""
    timestamp = published_at or _utc_now()
    reference_path = bundle_dir / config["databases"]["source_bundle"]["reference"]
    mapping_path = bundle_dir / config["databases"]["source_bundle"]["mapping"]
    reference_tables = build_reference_database(
        reference_path,
        source_run_id=source_run_id,
        published_at=timestamp,
    )
    mapping_tables = build_mapping_database(
        mapping_path,
        config,
        source_run_id=source_run_id,
        published_at=timestamp,
    )
    return {
        "source_run_id": source_run_id,
        "catalog_version": CATALOG_VERSION,
        "published_at": timestamp,
        "reference_database": str(reference_path),
        "mapping_database": str(mapping_path),
        "database": str(mapping_path),
        "schema_versions": {
            "reference": REFERENCE_SCHEMA_VERSION,
            "mapping": MAPPING_SCHEMA_VERSION,
        },
        "tables": {
            "reference.duckdb": reference_tables,
            "mapping.duckdb": mapping_tables,
        },
    }


def publish_control_catalog(config: dict[str, Any]) -> dict[str, Any]:
    """Compatibility builder; source publication owns pointer promotion."""
    runtime_home = Path(config["paths"]["runtime_home"]).resolve()
    run_id = f"source-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = runtime_home / "source_bundles" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return publish_source_catalogs(config, run_dir, run_id)
