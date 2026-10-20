# ruff: noqa: N999
"""Stage 4: create a self-contained Serving database and compatible views."""

from data_operations.pipeline.pipeline.database_staging import (
    attach_read_only,
    open_staging_database,
    table_names,
)
from data_operations.pipeline.pipeline.gold.serving_views import (
    SERVING_VIEWS,
    build_serving_views,
)
from data_operations.pipeline.pipeline.run_state import PipelineRun


def run(config: dict, candidate: PipelineRun) -> dict[str, int]:
    """Copy promoted facts locally, compile every view, and seal Serving."""
    del config
    connection = open_staging_database(candidate.paths.database("serving", staging=True))
    try:
        attach_read_only(connection, candidate.paths.database("gold"), "gold")
        attach_read_only(connection, candidate.paths.database("silver"), "silver")
        gold_tables = [
            row[0]
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_catalog = 'gold' AND table_name LIKE 'gold_%'
                ORDER BY table_name
                """
            ).fetchall()
        ]
        for table in gold_tables:
            connection.execute(
                f'CREATE TABLE "{table}" AS SELECT * FROM gold."{table}"'
            )
        for table in ("slvr_ref_site", "slvr_prod_master"):
            connection.execute(
                f'CREATE TABLE "{table}" AS SELECT * FROM silver."{table}"'
            )
        view_count = build_serving_views(connection)
        counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in table_names(connection, prefix="gold_")
        }
        counts["serving_views"] = view_count
    finally:
        connection.close()

    candidate.validate_database("serving", list(SERVING_VIEWS))
    return counts
