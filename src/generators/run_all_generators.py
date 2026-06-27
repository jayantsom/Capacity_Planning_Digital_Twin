"""
Master runner: all raw data generators in dependency order.
"""

import time
from src.utils.db_utils import load_config
from src.utils.logger import logger

from src.generators.reference_data import generate_reference_data
from src.generators.product_master import generate_product_master_db
from src.generators.demand_forecast import generate_demand_forecast_db
from src.generators.target_test_time import generate_target_test_time_db
from src.generators.target_yield import generate_target_yield_db
from src.generators.site_equipment_inventory import (
    generate_site_equipment_inventory_db
)
from src.generators.site_soft import generate_site_soft_db
from src.generators.mi_execution import generate_mi_execution_db
from src.generators.mi_test_param import generate_mi_test_param_db
from src.generators.mi_logs import generate_mi_logs_db


def run_all(config: dict) -> None:
    start = time.time()
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║     CAPACITY PLANNING DIGITAL TWIN — DATA GENERATION    ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")

    logger.info("\n── PASS 1: Reference Data ──────────────────────────────────")
    site_df, test_type_df, equip_df = generate_reference_data(config)

    logger.info("\n── PASS 2: Master Data ─────────────────────────────────────")
    product_df = generate_product_master_db(config)

    logger.info("\n── PASS 3: Planning Data ───────────────────────────────────")
    demand_df    = generate_demand_forecast_db(config)
    ttt_df       = generate_target_test_time_db(config)
    yield_df     = generate_target_yield_db(config)
    equip_inv_df = generate_site_equipment_inventory_db(config)
    site_soft_df = generate_site_soft_db(config)

    logger.info("\n── PASS 4: Execution Data ──────────────────────────────────")
    generate_mi_execution_db(config)
    generate_mi_test_param_db(config)
    generate_mi_logs_db(config)

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
    logger.info(f"  MI execution:  [see per-month logs above]")
    logger.info(f"  MI test param: [see per-month logs above]")
    logger.info(f"  MI logs:       [see per-month logs above]")
    logger.info(f"\n  Total wall time: {elapsed:.1f}s")
    logger.success("ALL GENERATORS COMPLETE.")


if __name__ == "__main__":
    cfg = load_config()
    run_all(cfg)