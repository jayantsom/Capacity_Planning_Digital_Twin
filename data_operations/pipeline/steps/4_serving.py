# ruff: noqa: N999
"""Stage 4: create a self-contained Serving database and compatible views."""

from data_operations.pipeline.pipeline.database_staging import (
    attach_read_only,
    open_staging_database,
)
from data_operations.pipeline.pipeline.gold.serving_views import (
    SERVING_VIEWS,
    build_serving_views,
)
from data_operations.pipeline.pipeline.run_state import PipelineRun


def run(config: dict, candidate: PipelineRun) -> dict[str, int]:
    """Materialize only self-contained srv_* contracts and seal Serving."""
    del config
    connection = open_staging_database(candidate.paths.database("serving", staging=True))
    try:
        attach_read_only(connection, candidate.paths.database("gold"), "gold")
        attach_read_only(connection, candidate.paths.database("silver"), "silver")
        for alias, prefix in (("gold", "gold_"), ("silver", "slvr_")):
            rows = connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_catalog = ? AND table_name LIKE ?
                """,
                [alias, f"{prefix}%"],
            ).fetchall()
            for (table,) in rows:
                connection.execute(
                    f'CREATE OR REPLACE TEMP VIEW "{table}" AS '
                    f'SELECT * FROM {alias}."{table}"'
                )
        view_count = build_serving_views(connection)
        local_objects = connection.execute(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_catalog = current_database()
            """
        ).fetchall()
        invalid = [
            (name, object_type)
            for name, object_type in local_objects
            if not name.startswith("srv_") or object_type != "BASE TABLE"
        ]
        if invalid:
            raise ValueError(f"Serving publication ownership violation: {invalid}")
        counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in SERVING_VIEWS
        }
        counts["serving_tables"] = view_count
    finally:
        connection.close()

    candidate.validate_database("serving", list(SERVING_VIEWS))
    return counts
