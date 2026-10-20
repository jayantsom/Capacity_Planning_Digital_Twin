"""
Silver layer master runner.
Orchestrates all Bronze → Silver transformations in correct order.
"""

import time
import uuid
from datetime import UTC, datetime

import duckdb

from capacity_twin_core.logging import logger
from capacity_twin_core.runtime.database_paths import get_duckdb_connection, load_config
from data_operations.pipeline.pipeline.bronze.schema import BRONZE_CONFIGS
from data_operations.pipeline.pipeline.silver.transforms_mi import (
    transform_mi_execution,
    transform_mi_logs,
    transform_mi_test_param,
)
from data_operations.pipeline.pipeline.silver.transforms_planning import (
    transform_demand_requirements,
    transform_site_equipment_inventory,
    transform_site_soft,
    transform_target_test_time,
    transform_target_yield,
)
from data_operations.pipeline.pipeline.silver.transforms_reference import (
    transform_product_tables,
    transform_reference_tables,
)
from data_operations.pipeline.spark.session import get_spark_session


def _build_quarantine(duck_conn, run_id: str, ts: str) -> int:
    """Persist rejected source truth as auditable JSON records."""
    duck_conn.execute("DROP TABLE IF EXISTS slvr_quarantine")
    duck_conn.execute(
        """
        CREATE TABLE slvr_quarantine (
            quarantine_id VARCHAR,
            origin_layer VARCHAR,
            source_table VARCHAR,
            bronze_id VARCHAR,
            invalid_reason VARCHAR,
            payload_json JSON,
            pipeline_run_id VARCHAR,
            quarantined_at VARCHAR
        )
        """
    )
    for table_config in BRONZE_CONFIGS:
        table = table_config.bronze_table
        duck_conn.execute(
            f"""
            INSERT INTO slvr_quarantine
            SELECT
                md5('{table}|' || bronze_id || '|BRONZE'),
                'BRONZE',
                '{table}',
                bronze_id,
                invalid_reason,
                to_json(source_row),
                ?,
                ?
            FROM "{table}" AS source_row
            WHERE NOT is_valid
            """,
            [run_id, ts],
        )

    count = duck_conn.execute("SELECT COUNT(*) FROM slvr_quarantine").fetchone()[0]
    duck_conn.execute(
        """
        CREATE INDEX idx_slvr_quarantine_source
        ON slvr_quarantine (source_table)
        """
    )
    return count


def run_silver_transforms(
    config: dict,
    *,
    duck_conn: duckdb.DuckDBPyConnection | None = None,
    pipeline_run_id: str | None = None,
) -> dict[str, int]:
    start = time.time()
    run_id = pipeline_run_id or str(uuid.uuid4())
    ts = datetime.now(UTC).isoformat()

    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║              SILVER LAYER — TRANSFORMATIONS              ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    logger.info(f"  Pipeline run ID: {run_id}")

    spark     = get_spark_session()
    owns_connection = duck_conn is None
    duck_conn = duck_conn or get_duckdb_connection(config, database_key="silver")
    counts    = {}

    # ── Reference and master ───────────────────────────────────────────────
    logger.info("\n── Reference Tables ────────────────────────────────────────")
    counts.update(transform_reference_tables(duck_conn, spark, run_id, ts))

    logger.info("\n── Product Tables ──────────────────────────────────────────")
    counts.update(transform_product_tables(duck_conn, spark, run_id, ts))

    # ── Planning tables ────────────────────────────────────────────────────
    logger.info("\n── Planning Tables ─────────────────────────────────────────")
    counts["slvr_demand_requirement"] = transform_demand_requirements(
        duck_conn, run_id, ts
    )
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
    counts["slvr_quarantine"] = _build_quarantine(duck_conn, run_id, ts)

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
    if owns_connection:
        duck_conn.close()
    return counts


if __name__ == "__main__":
    cfg = load_config()
    run_silver_transforms(cfg)