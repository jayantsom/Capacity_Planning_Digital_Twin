# ruff: noqa: N999
"""Stage 2: clean Bronze data and retain rejected records for audit."""

from data_operations.pipeline.pipeline.database_staging import (
    attach_read_only,
    expose_tables,
    open_staging_database,
)
from data_operations.pipeline.pipeline.run_state import PipelineRun
from data_operations.pipeline.pipeline.silver.run_silver import run_silver_transforms

REQUIRED_TABLES = [
    "slvr_ref_site",
    "slvr_ref_test_type",
    "slvr_ref_equipment",
    "slvr_prod_master",
    "slvr_prod_hierarchy",
    "slvr_demand_requirement",
    "slvr_tgt_test_time",
    "slvr_tgt_yield",
    "slvr_site_equip_inv",
    "slvr_site_soft",
    "slvr_mi_execution",
    "slvr_mi_test_param",
    "slvr_mi_logs",
    "slvr_quarantine",
]


def run(config: dict, candidate: PipelineRun) -> dict[str, int]:
    """Build and seal silver.duckdb from read-only Bronze."""
    connection = open_staging_database(candidate.paths.database("silver", staging=True))
    try:
        attach_read_only(connection, candidate.paths.database("bronze"), "bronze")
        expose_tables(connection, "bronze", "brnz_")
        counts = run_silver_transforms(
            config,
            duck_conn=connection,
            pipeline_run_id=candidate.paths.run_id,
        )
    finally:
        connection.close()
    candidate.validate_database("silver", REQUIRED_TABLES)
    return counts
