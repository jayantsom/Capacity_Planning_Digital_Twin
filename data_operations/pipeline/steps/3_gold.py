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
    "gold_operational_performance",
    "gold_operational_events",
    "gold_forecast_accuracy",
    "gold_cap_actual",
    "gold_demonstrated_capacity",
    "gold_ml_feature_store",
    "gold_equipment_cost_reference",
]


def _validate_capacity_contracts(connection) -> None:
    """Block promotion when governed capacity contracts are incomplete."""
    missing_behavior = connection.execute(
        """
        SELECT COUNT(*)
        FROM gold_gcm_base
        WHERE resource_behavior IS NULL OR TRIM(resource_behavior) = ''
        """
    ).fetchone()[0]
    if missing_behavior:
        raise ValueError("Gold contains rows without a governed resource behavior")

    fanout_errors = connection.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT site_code, product_number, route_step_id, month_key,
                   planning_version_id, resource_behavior,
                   SUM(effective_demand_qty) AS allocated_demand,
                   MAX(route_step_demand_qty) AS route_step_demand
            FROM gold_gcm_base
            WHERE resource_behavior IN ('ALTERNATIVE_POOL', 'SHARED_POOL')
            GROUP BY ALL
            HAVING ABS(allocated_demand - route_step_demand) > 0.001
        )
        """
    ).fetchone()[0]
    if fanout_errors:
        raise ValueError("Alternative resource fan-out does not conserve demand")

    for table, mode in (
        ("gold_cap_normal", "NORMAL"),
        ("gold_cap_maximum", "MAXIMUM"),
    ):
        modes = {
            row[0]
            for row in connection.execute(
                f'SELECT DISTINCT capacity_mode FROM "{table}"'
            ).fetchall()
        }
        retest_modes = {
            row[0]
            for row in connection.execute(
                f'SELECT DISTINCT retest_type FROM "{table}"'
            ).fetchall()
        }
        if modes != {mode} or retest_modes != {"NONE", "TYPE1", "TYPE2"}:
            raise ValueError(f"{table} is missing a governed capacity or retest mode")

    published_modes = {
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT capacity_mode FROM gold_dmnd_vs_cap"
        ).fetchall()
    }
    if published_modes != {"NORMAL", "MAXIMUM"}:
        raise ValueError("Demand versus capacity must publish Normal and Maximum")

    actual_columns = {
        row[0]
        for row in connection.execute("DESCRIBE gold_cap_actual").fetchall()
    }
    if "planning_version_id" in actual_columns:
        raise ValueError("Actual Output must not carry a planning version")

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
        _validate_capacity_contracts(connection)
    finally:
        connection.close()
    candidate.validate_database("gold", REQUIRED_TABLES)
    return counts
