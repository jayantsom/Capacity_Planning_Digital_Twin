"""
Generator: raw_target_yield.db
Monthly target yield per site-product-test_type combination.
"""

import numpy as np
import pandas as pd

from capacity_twin_core.dates.months import get_all_month_keys, month_key_label
from capacity_twin_core.domain.constants import (
    FORECAST_SOURCE_PLANNER,
    RANDOM_SEED,
)
from capacity_twin_core.logging import logger
from capacity_twin_core.runtime.database_paths import get_sqlite_path, load_config
from data_operations.generator.generators.assignment_matrix import ASSIGNMENT_MATRIX
from data_operations.generator.generators.reference_data import TEST_TYPES, write_to_sqlite
from data_operations.generator.rules.contracts import DateContract
from data_operations.generator.rules.determinism import stable_seed
from data_operations.generator.services.control_catalog import load_assignments

# ── Base yield ranges by test type ────────────────────────────────────────────
YIELD_BASE = {
    "ICT": (0.92, 0.98),
    "FCT": (0.88, 0.96),
    "TRX": (0.85, 0.95),
    "UC":  (0.90, 0.98),
    "OTA": (0.82, 0.94),
    "PIM": (0.88, 0.96),
    "PAM": (0.84, 0.94),
    "BIT": (0.95, 0.99),
    "ALT": (0.90, 0.97),
    "AT":  (0.88, 0.96),
}

TEST_TYPE_META = {t[0]: (t[2], t[5]) for t in TEST_TYPES}

# Site quality factor — some suppliers have tighter process control
SITE_QUALITY_FACTORS = {
    "ERV_STK": 1.02, "ERV_TAL": 0.99, "ERV_MAD": 1.00, "ERV_GDN": 0.99,
    "ERV_BUD": 0.99, "ERV_MOS": 0.97, "JAB_GDL": 0.98, "JAB_PUN": 0.97,
    "JAB_SGP": 1.01, "JAB_BEL": 0.97, "FLX_HCM": 0.98, "FLX_SZN": 1.00,
    "FLX_SAO": 0.97, "INF_MUN": 1.02, "INF_SEO": 1.01, "INF_TSE": 1.02,
    "SAN_AUS": 1.00, "SAN_MXC": 0.98, "SAN_PEN": 0.99, "LUX_SZN": 0.99,
    "LUX_TWN": 1.00, "LUX_HNI": 0.97,
}


def generate_yield_for_planning_version(
    planning_version_id: str,
    plan_as_of_date: str,
    all_month_keys: list[int],
    root_seed: int = RANDOM_SEED,
    assignments: list[dict] | None = None,
) -> pd.DataFrame:
    rows = []

    for assignment in assignments or ASSIGNMENT_MATRIX:
        site_code   = assignment["site_code"]
        product_num = assignment["product_number"]
        family      = assignment["product_family"]
        platform    = assignment["platform"]
        test_types  = assignment["test_types"]

        site_quality = SITE_QUALITY_FACTORS.get(site_code, 1.0)

        for tt in test_types:
            base_min, base_max = YIELD_BASE.get(tt, (0.85, 0.95))
            cat_id, responsible = TEST_TYPE_META.get(tt, ("999999", "Unknown"))

            seed_val = stable_seed(
                root_seed, site_code, product_num, tt, "target-yield"
            )
            local_rng = np.random.default_rng(seed_val)

            # Base yield adjusted for site quality
            base_yield = local_rng.uniform(base_min, base_max) * site_quality

            yield_row = {
                "platform":           platform,
                "product_family":     family,
                "site":               site_code,
                "responsible_person": responsible,
                "product_number":     product_num,
                "test_type":          tt,
                "test_category_id":   cat_id,
                "planning_version_id":        planning_version_id,
                "plan_as_of_date":      plan_as_of_date,
                "forecast_source":    FORECAST_SOURCE_PLANNER,
            }

            for i, mk in enumerate(all_month_keys):
                # Slow continuous improvement +0.1-0.3%/month.
                learning = (1 + local_rng.uniform(0.001, 0.003)) ** i

                noise = local_rng.normal(0, 0.005)
                yield_val = base_yield * learning + noise
                yield_val = float(np.clip(yield_val, 0.50, 0.99))

                col = month_key_label(mk)
                yield_row[col] = (
                    None if yield_val is None
                    else round(yield_val, 4)
                )

            rows.append(yield_row)

    return pd.DataFrame(rows)


def generate_target_yield_db(config: dict) -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("GENERATING: raw_target_yield.db")
    logger.info("=" * 60)

    db_path = get_sqlite_path(config["databases"]["raw"]["yield"], config)

    dates = DateContract.from_config(config)
    all_month_keys = get_all_month_keys(dates.actual_start, dates.forecast_end)
    planning_versions = [
        (f"plan-{plan_as_of_date.isoformat()}", plan_as_of_date.isoformat())
        for plan_as_of_date in dates.plan_as_of_dates
    ]
    assignments = load_assignments(config)

    all_dfs = []
    for planning_version_id, plan_as_of_date in planning_versions:
        logger.info(f"  Generating planning version: {planning_version_id}")
        df = generate_yield_for_planning_version(
            planning_version_id,
            plan_as_of_date,
            all_month_keys,
            int(config["data_generation"]["random_seed"]),
            assignments,
        )
        all_dfs.append(df)
        logger.info(f"    Rows: {len(df):,}")

    combined = pd.concat(all_dfs, ignore_index=True)
    write_to_sqlite(combined, "target_yield", db_path)

    logger.info(f"  Total rows: {len(combined):,}")
    logger.success("raw_target_yield.db complete")
    return combined


if __name__ == "__main__":
    cfg = load_config()
    generate_target_yield_db(cfg)