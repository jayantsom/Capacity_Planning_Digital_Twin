# ruff: noqa: N999
"""Stage 1: preserve Raw SQLite truth in a validated Bronze candidate."""

from data_operations.pipeline.pipeline.bronze.ingest import run_bronze_ingestion
from data_operations.pipeline.pipeline.bronze.schema import BRONZE_CONFIGS
from data_operations.pipeline.pipeline.database_staging import open_staging_database
from data_operations.pipeline.pipeline.run_state import PipelineRun


def run(config: dict, candidate: PipelineRun) -> dict[str, int]:
    """Build and seal bronze.duckdb."""
    connection = open_staging_database(candidate.paths.database("bronze", staging=True))
    try:
        summaries = run_bronze_ingestion(
            config,
            duck_conn=connection,
            pipeline_run_id=candidate.paths.run_id,
        )
    finally:
        connection.close()

    candidate.validate_database(
        "bronze", [table.bronze_table for table in BRONZE_CONFIGS]
    )
    return {item["table"]: item["rows_read"] for item in summaries}
