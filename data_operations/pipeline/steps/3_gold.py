# ruff: noqa: N999
"""Stage 3: publish checked capacity facts from read-only Silver."""

from data_operations.pipeline.pipeline.database_staging import (
    attach_read_only,
    expose_tables,
    open_staging_database,
)
from data_operations.pipeline.pipeline.gold.run_gold import run_gold_pipeline
from data_operations.pipeline.pipeline.run_state import PipelineRun

REQUIRED_TABLES = [
    "gold_gcm_base",
    "gold_cap_normal",
    "gold_cap_maximum",
    "gold_resource_scenarios",
    "gold_dmnd_vs_cap",
    "gold_bottleneck",
    "gold_oee_metrics",
    "gold_forecast_accuracy",
    "gold_cap_actual",
    "gold_ml_feature_store",
]


def run(config: dict, candidate: PipelineRun) -> dict[str, int]:
    """Build and seal gold.duckdb from read-only Silver."""
    connection = open_staging_database(candidate.paths.database("gold", staging=True))
    try:
        attach_read_only(connection, candidate.paths.database("silver"), "silver")
        expose_tables(connection, "silver", "slvr_")
        counts = run_gold_pipeline(
            config,
            duck_conn=connection,
            pipeline_run_id=candidate.paths.run_id,
        )
    finally:
        connection.close()
    candidate.validate_database("gold", REQUIRED_TABLES)
    return counts
