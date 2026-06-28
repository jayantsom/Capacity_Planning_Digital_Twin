"""
Gold layer master runner.
Orchestrates GCM base → capacity math → analytics → serving views.
"""

import time
import uuid
from datetime import datetime, timezone

from src.utils.db_utils import load_config, get_duckdb_connection
from src.pipeline.gold.gcm_base import build_gcm_base
from src.pipeline.gold.capacity_math import build_capacity_tables
from src.pipeline.gold.analytics import (
    build_demand_vs_capacity,
    build_bottleneck_table,
    build_oee_metrics,
    build_forecast_accuracy,
    build_actual_capacity,
    build_ml_feature_store,
)
from src.pipeline.gold.serving_views import build_serving_views
from src.utils.logger import logger


def run_gold_pipeline(config: dict) -> None:
    start  = time.time()
    run_id = str(uuid.uuid4())

    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║               GOLD LAYER — CAPACITY MATH                ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    logger.info(f"  Pipeline run ID: {run_id}")

    duck_conn = get_duckdb_connection(config)
    counts = {}

    # Step 1: GCM base join
    logger.info("\n── Step 1: GCM Base Join ───────────────────────────────────")
    counts["gold_gcm_base"] = build_gcm_base(duck_conn)

    # Step 2: Capacity math
    logger.info("\n── Step 2: Capacity Calculations ───────────────────────────")
    cap_counts = build_capacity_tables(duck_conn)
    counts.update(cap_counts)

    # Step 3: Analytics tables
    logger.info("\n── Step 3: Analytics Tables ────────────────────────────────")
    counts["gold_dmnd_vs_cap"]       = build_demand_vs_capacity(duck_conn)
    counts["gold_bottleneck"]        = build_bottleneck_table(duck_conn)
    counts["gold_oee_metrics"]       = build_oee_metrics(duck_conn)
    counts["gold_forecast_accuracy"] = build_forecast_accuracy(duck_conn)
    counts["gold_cap_actual"]        = build_actual_capacity(duck_conn)
    counts["gold_ml_feature_store"]  = build_ml_feature_store(duck_conn)

    # Step 4: Serving views
    logger.info("\n── Step 4: Serving Views ───────────────────────────────────")
    counts["serving_views"] = build_serving_views(duck_conn)

    # Summary
    elapsed = time.time() - start
    logger.info("\n╔══════════════════════════════════════════════════════════╗")
    logger.info("║                   GOLD SUMMARY                          ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    for table, count in sorted(counts.items()):
        logger.info(f"  {table:<40} {count:>10,}")
    logger.info(f"\n  Wall time: {elapsed:.1f}s")
    logger.success("Gold pipeline complete.")

    duck_conn.close()


if __name__ == "__main__":
    cfg = load_config()
    run_gold_pipeline(cfg)