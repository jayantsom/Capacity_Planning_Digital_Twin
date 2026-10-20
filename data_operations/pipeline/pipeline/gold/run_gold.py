"""
Gold layer master runner.
Orchestrates GCM base → capacity math → analytics → serving views.
"""

import time
import uuid

import duckdb

from capacity_twin_core.logging import logger
from capacity_twin_core.runtime.database_paths import get_duckdb_connection, load_config
from data_operations.pipeline.pipeline.database_staging import assert_unique_grain
from data_operations.pipeline.pipeline.gold.analytics import (
    build_actual_capacity,
    build_bottleneck_table,
    build_demand_vs_capacity,
    build_forecast_accuracy,
    build_ml_feature_store,
    build_oee_metrics,
)
from data_operations.pipeline.pipeline.gold.capacity_math import (
    build_capacity_tables,
    build_resource_scenario_table,
)
from data_operations.pipeline.pipeline.gold.gcm_base import build_gcm_base


def run_gold_pipeline(
    config: dict,
    *,
    duck_conn: duckdb.DuckDBPyConnection | None = None,
    pipeline_run_id: str | None = None,
) -> dict[str, int]:
    start  = time.time()
    run_id = pipeline_run_id or str(uuid.uuid4())

    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║               GOLD LAYER — CAPACITY MATH                ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    logger.info(f"  Pipeline run ID: {run_id}")

    owns_connection = duck_conn is None
    duck_conn = duck_conn or get_duckdb_connection(config, database_key="gold")
    counts = {}

    # Step 1: GCM base join
    logger.info("\n── Step 1: GCM Base Join ───────────────────────────────────")
    counts["gold_gcm_base"] = build_gcm_base(duck_conn)

    # Step 2: Capacity math
    logger.info("\n── Step 2: Capacity Calculations ───────────────────────────")
    cap_counts = build_capacity_tables(duck_conn)
    counts.update(cap_counts)
    counts["gold_resource_scenarios"] = build_resource_scenario_table(duck_conn)

    # Step 3: Analytics tables
    logger.info("\n── Step 3: Analytics Tables ────────────────────────────────")
    counts["gold_dmnd_vs_cap"]       = build_demand_vs_capacity(duck_conn)
    counts["gold_bottleneck"]        = build_bottleneck_table(duck_conn)
    counts["gold_oee_metrics"]       = build_oee_metrics(duck_conn)
    counts["gold_forecast_accuracy"] = build_forecast_accuracy(duck_conn)
    counts["gold_cap_actual"]        = build_actual_capacity(duck_conn)
    counts["gold_ml_feature_store"]  = build_ml_feature_store(duck_conn)
    assert_unique_grain(duck_conn, "gold_gcm_base", ["gcm_pk"])
    assert_unique_grain(duck_conn, "gold_dmnd_vs_cap", ["gap_pk"])
    assert_unique_grain(
        duck_conn,
        "gold_cap_actual",
        [
            "site_code",
            "product_number",
            "test_type",
            "month_key",
            "snapshot_id",
        ],
    )
    assert_unique_grain(
        duck_conn,
        "gold_ml_feature_store",
        [
            "site_code",
            "product_number",
            "test_type",
            "month_key",
            "snapshot_id",
        ],
    )

    # Summary
    elapsed = time.time() - start
    logger.info("\n╔══════════════════════════════════════════════════════════╗")
    logger.info("║                   GOLD SUMMARY                          ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    for table, count in sorted(counts.items()):
        logger.info(f"  {table:<40} {count:>10,}")
    logger.info(f"\n  Wall time: {elapsed:.1f}s")
    logger.success("Gold pipeline complete.")

    if owns_connection:
        duck_conn.close()
    return counts


if __name__ == "__main__":
    cfg = load_config()
    run_gold_pipeline(cfg)