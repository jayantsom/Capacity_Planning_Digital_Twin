"""
Master runner: executes all raw data generators in dependency order.
Run this once to populate all 10 SQLite source databases.
"""

import time
from src.utils.db_utils import load_config
from src.utils.logger import logger

from src.generators.reference_data import generate_reference_data
from src.generators.product_master import generate_product_master_db


def run_all(config: dict) -> None:
    start = time.time()
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║     CAPACITY PLANNING DIGITAL TWIN — DATA GENERATION    ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")

    # Pass 1: Reference data (no dependencies)
    logger.info("\n── PASS 1: Reference Data ──────────────────────────────────")
    site_df, test_type_df, equip_df = generate_reference_data(config)

    # Pass 2: Master data
    logger.info("\n── PASS 2: Master Data ─────────────────────────────────────")
    product_df = generate_product_master_db(config)

    # Pass 3-4: Planning + Execution (stubs — to be added next)
    logger.info("\n── PASS 3-4: Planning + Execution (coming next) ────────────")
    logger.info("  [stub] demand_forecast, target_test_time, target_yield,")
    logger.info("         site_equip_inv, site_soft, mi_execution,")
    logger.info("         mi_test_param, mi_logs")

    elapsed = time.time() - start
    logger.info(f"\n✓ Generation complete in {elapsed:.1f}s")
    logger.info(f"  Reference: {len(site_df)} sites | "
                f"{len(test_type_df)} test types | "
                f"{len(equip_df)} equipment")
    logger.info(f"  Products:  {len(product_df)} records")


if __name__ == "__main__":
    cfg = load_config()
    run_all(cfg)