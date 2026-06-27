"""
Master runner: executes all raw data generators in dependency order.
"""

import time
from src.utils.db_utils import load_config
from src.utils.logger import logger

from src.generators.reference_data import generate_reference_data
from src.generators.product_master import generate_product_master_db
from src.generators.demand_forecast import generate_demand_forecast_db
from src.generators.target_test_time import generate_target_test_time_db
from src.generators.target_yield import generate_target_yield_db
from src.generators.site_equipment_inventory import generate_site_equipment_inventory_db
from src.generators.site_soft import generate_site_soft_db


def run_all(config: dict) -> None:
    start = time.time()
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║     CAPACITY PLANNING DIGITAL TWIN — DATA GENERATION    ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")

    # Pass 1: Reference
    logger.info("\n── PASS 1: Reference Data ──────────────────────────────────")
    site_df, test_type_df, equip_df = generate_reference_data(config)

    # Pass 2: Master
    logger.info("\n── PASS 2: Master Data ─────────────────────────────────────")
    product_df = generate_product_master_db(config)

    # Pass 3: Planning
    logger.info("\n── PASS 3: Planning Data ───────────────────────────────────")
    demand_df  = generate_demand_forecast_db(config)
    ttt_df     = generate_target_test_time_db(config)
    yield_df   = generate_target_yield_db(config)
    equip_inv_df = generate_site_equipment_inventory_db(config)
    site_soft_df = generate_site_soft_db(config)

    # Pass 4: Execution (coming next step)
    logger.info("\n── PASS 4: Execution Data (coming next) ────────────────────")
    logger.info("  [stub] mi_execution, mi_test_param, mi_logs")

    elapsed = time.time() - start
    logger.info("\n╔══════════════════════════════════════════════════════════╗")
    logger.info("║                  GENERATION SUMMARY                     ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    logger.info(f"  Reference:     {len(site_df)} sites | "
                f"{len(test_type_df)} test types | "
                f"{len(equip_df)} equipment")
    logger.info(f"  Products:      {len(product_df)} records")
    logger.info(f"  Demand:        {len(demand_df):,} rows")
    logger.info(f"  Test time:     {len(ttt_df):,} rows")
    logger.info(f"  Yield:         {len(yield_df):,} rows")
    logger.info(f"  Equipment inv: {len(equip_inv_df):,} rows")
    logger.info(f"  Site soft:     {len(site_soft_df):,} rows")
    logger.info(f"\n  Total time: {elapsed:.1f}s")
    logger.success("All planning data generators complete.")


if __name__ == "__main__":
    cfg = load_config()
    run_all(cfg)