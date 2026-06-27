"""
Silver layer master runner.
Orchestrates all Bronze → Silver transformations in correct order.
"""

import time
import uuid
from datetime import datetime, timezone

from src.utils.spark_utils import get_spark_session
from src.utils.db_utils import load_config, get_duckdb_connection
from src.pipeline.silver.transforms_reference import (
    transform_reference_tables, transform_product_tables
)
from src.pipeline.silver.transforms_planning import (
    transform_demand_forecast,
    transform_target_test_time,
    transform_target_yield,
    transform_site_equipment_inventory,
    transform_site_soft,
)
from src.pipeline.silver.transforms_mi import (
    transform_mi_execution,
    transform_mi_test_param,
    transform_mi_logs,
)
from src.utils.logger import logger


def run_silver_transforms(config: dict) -> None:
    start = time.time()
    run_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()

    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║              SILVER LAYER — TRANSFORMATIONS              ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    logger.info(f"  Pipeline run ID: {run_id}")

    spark     = get_spark_session()
    duck_conn = get_duckdb_connection(config)
    counts    = {}

    # ── Reference and master ───────────────────────────────────────────────
    logger.info("\n── Reference Tables ────────────────────────────────────────")
    counts.update(transform_reference_tables(duck_conn, spark, run_id, ts))

    logger.info("\n── Product Tables ──────────────────────────────────────────")
    counts.update(transform_product_tables(duck_conn, spark, run_id, ts))

    # ── Planning tables ────────────────────────────────────────────────────
    logger.info("\n── Planning Tables ─────────────────────────────────────────")
    counts["slvr_dmnd_forecast"] = transform_demand_forecast(
        duck_conn, spark, run_id, ts)
    counts["slvr_tgt_test_time"] = transform_target_test_time(
        duck_conn, spark, run_id, ts)
    counts["slvr_tgt_yield"]     = transform_target_yield(
        duck_conn, spark, run_id, ts)
    counts["slvr_site_equip_inv"] = transform_site_equipment_inventory(
        duck_conn, spark, run_id, ts)
    counts["slvr_site_soft"]     = transform_site_soft(
        duck_conn, spark, run_id, ts)

    # ── MI tables (chunked) ────────────────────────────────────────────────
    logger.info("\n── Manufacturing Intelligence Tables ───────────────────────")
    counts["slvr_mi_execution"]  = transform_mi_execution(
        duck_conn, spark, run_id, ts)
    counts["slvr_mi_test_param"] = transform_mi_test_param(
        duck_conn, spark, run_id, ts)
    counts["slvr_mi_logs"]       = transform_mi_logs(
        duck_conn, spark, run_id, ts)

    # ── Summary ────────────────────────────────────────────────────────────
    elapsed = time.time() - start
    logger.info("\n╔══════════════════════════════════════════════════════════╗")
    logger.info("║                  SILVER SUMMARY                         ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    total = 0
    for table, count in sorted(counts.items()):
        logger.info(f"  {table:<35} {count:>10,} rows")
        total += count
    logger.info(f"  {'─'*47}")
    logger.info(f"  {'TOTAL':<35} {total:>10,} rows")
    logger.info(f"\n  Wall time: {elapsed:.1f}s")
    logger.success("Silver transforms complete.")

    spark.stop()
    duck_conn.close()


if __name__ == "__main__":
    cfg = load_config()
    run_silver_transforms(cfg)