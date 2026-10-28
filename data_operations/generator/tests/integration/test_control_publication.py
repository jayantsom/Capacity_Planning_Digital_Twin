"""Control catalog ownership and publication contracts."""

from copy import deepcopy
from pathlib import Path

import duckdb

from capacity_twin_core.data.ownership import MAPPING_TABLES, REFERENCE_TABLES
from capacity_twin_core.runtime.database_paths import load_config
from data_operations.generator.services.control_publication import (
    publish_source_catalogs,
)


def test_control_publication_keeps_application_mappings_out_of_raw(
    tmp_path: Path,
) -> None:
    """Publish one immutable catalog containing only governed controls."""
    config = deepcopy(load_config())
    config["paths"]["runtime_home"] = str(tmp_path)
    bundle = tmp_path / "source_bundles" / "source-test"
    bundle.mkdir(parents=True)
    publication = publish_source_catalogs(config, bundle, "source-test")

    mapping = Path(publication["mapping_database"])
    reference = Path(publication["reference_database"])
    assert mapping.is_file()
    assert reference.is_file()
    with duckdb.connect(str(mapping), read_only=True) as connection:
        tables = {
            f"{row[0]}.{row[1]}"
            for row in connection.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                """
            ).fetchall()
        }
        assignments = connection.execute(
            "SELECT COUNT(*) FROM crosswalk.site_product_assignment"
        ).fetchone()[0]

    with duckdb.connect(str(reference), read_only=True) as connection:
        reference_tables = {
            f"{row[0]}.{row[1]}"
            for row in connection.execute(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                """
            ).fetchall()
        }

    assert tables == MAPPING_TABLES
    assert reference_tables == REFERENCE_TABLES
    assert assignments > 0
