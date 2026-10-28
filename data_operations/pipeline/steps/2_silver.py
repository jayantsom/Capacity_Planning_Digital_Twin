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
    "slvr_manufacturer_master",
    "slvr_product_bom",
    "slvr_product_route",
    "slvr_route_step",
    "slvr_site_product_source",
    "slvr_resource_contract",
    "slvr_source_publication",
    "slvr_demand_requirement",
    "slvr_tgt_test_time",
    "slvr_tgt_yield",
    "slvr_site_equip_inv",
    "slvr_site_soft",
    "slvr_machine_execution",
    "slvr_machine_test_param",
    "slvr_machine_logs",
    "slvr_equipment_cost_reference",
    "slvr_quarantine",
]


def run(config: dict, candidate: PipelineRun) -> dict[str, int]:
    """Build and seal silver.duckdb from read-only Bronze."""
    connection = open_staging_database(candidate.paths.database("silver", staging=True))
    try:
        attach_read_only(connection, candidate.paths.database("bronze"), "bronze")
        attach_read_only(connection, candidate.source_reference_database, "reference")
        attach_read_only(connection, candidate.source_mapping_database, "mapping")
        expose_tables(connection, "bronze", "brnz_")
        counts = run_silver_transforms(
            config,
            duck_conn=connection,
            pipeline_run_id=candidate.paths.run_id,
            source_run_id=candidate.source_run_id,
            source_bundle_checksum=candidate.source_bundle_checksum,
        )
    finally:
        connection.close()
    candidate.validate_database("silver", REQUIRED_TABLES)
    return counts
