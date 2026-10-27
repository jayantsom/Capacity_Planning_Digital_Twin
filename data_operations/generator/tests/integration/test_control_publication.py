"""Control catalog ownership and publication contracts."""

from copy import deepcopy
from pathlib import Path

import duckdb

from capacity_twin_core.data.ownership import APPLICATION_CONTROL_TABLES
from capacity_twin_core.runtime.database_paths import load_config
from data_operations.generator.services.control_publication import (
    publish_control_catalog,
)


def test_control_publication_keeps_application_mappings_out_of_raw(
    tmp_path: Path,
) -> None:
    """Publish one immutable catalog containing only governed controls."""
    config = deepcopy(load_config())
    config["paths"]["runtime_home"] = str(tmp_path)
    pointer = publish_control_catalog(config)

    database = Path(pointer["database"])
    assert database.is_file()
    with duckdb.connect(str(database), read_only=True) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                """
            ).fetchall()
        }
        assignments = connection.execute(
            "SELECT COUNT(*) FROM crosswalk.site_product_assignment"
        ).fetchone()[0]

    assert tables == APPLICATION_CONTROL_TABLES
    assert assignments > 0
    assert (tmp_path / "control_current.json").is_file()
