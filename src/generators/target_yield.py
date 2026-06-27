"""
Generator: raw_target_yield.db
Monthly target yield per site-product-test_type combination.
"""

import numpy as np
import pandas as pd

from config.constants import (
    RANDOM_SEED, SNAPSHOT_1_ID, SNAPSHOT_2_ID,
    SNAPSHOT_1_DATE, SNAPSHOT_2_DATE,
    FORECAST_SOURCE_PLANNER,
)
from src.utils.db_utils import load_config, get_sqlite_path
from src.utils.month_utils import get_all_month_keys, month_key_label
from src.generators.assignment_matrix import ASSIGNMENT_MATRIX
from src.generators.reference_data import write_to_sqlite, TEST_TYPES
from src.utils.logger import logger


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
    "ERI_STK": 1.02, "ERI_TAL": 0.99, "ERI_MAD": 1.00, "ERI_GDN": 0.99,
    "ERI_BUD": 0.99, "ERI_MOS": 0.97, "JAB_GDL": 0.98, "JAB_PUN": 0.97,
    "JAB_SGP": 1.01, "JAB_BEL": 0.97, "FLX_HCM": 0.98, "FLX_SZN": 1.00,
    "FLX_SAO": 0.97, "INF_MUN": 1.02, "INF_SEO": 1.01, "INF_TSE": 1.02,
    "SAN_AUS": 1.00, "SAN_MXC": 0.98, "SAN_PEN": 0.99, "LUX_SZN": 0.99,
    "LUX_TWN": 1.00, "LUX_HNI": 0.97,
}


def generate_yield_for_snapshot(
    snapshot_id: str,
    snapshot_date: str,
    all_month_keys: list[int],
) -> pd.DataFrame:
    rows = []

    for assignment in ASSIGNMENT_MATRIX:
        site_code   = assignment["site_code"]
        product_num = assignment["product_number"]
        family      = assignment["product_family"]
        platform    = assignment["platform"]
        status      = assignment["product_status"]
        test_types  = assignment["test_types"]

        site_quality = SITE_QUALITY_FACTORS.get(site_code, 1.0)

        for tt in test_types:
            base_min, base_max = YIELD_BASE.get(tt, (0.85, 0.95))
            cat_id, responsible = TEST_TYPE_META.get(tt, ("999999", "Unknown"))

            seed_val = hash(
                f"{site_code}|{product_num}|{tt}|yield|{snapshot_id}"
            ) % (2**31)
            local_rng = np.random.default_rng(seed_val)

            # Base yield adjusted for site quality
            base_yield = local_rng.uniform(base_min, base_max) * site_quality

            # NPI: starts 12% lower, improves over 12 months
            npi_initial_penalty = 0.88 if status == "NPI" else 1.0

            yield_row = {
                "platform":           platform,
                "product_family":     family,
                "site":               site_code,
                "responsible_person": responsible,
                "product_number":     product_num,
                "test_type":          tt,
                "test_category_id":   cat_id,
                "snapshot_id":        snapshot_id,
                "snapshot_date":      snapshot_date,
                "forecast_source":    FORECAST_SOURCE_PLANNER,
            }

            for i, mk in enumerate(all_month_keys):
                if status == "NPI":
                    npi_months = min(i, 12)
                    improvement = npi_initial_penalty + (
                        (1.0 - npi_initial_penalty) * npi_months / 12
                    )
                    learning = (1 + 0.001) ** max(0, i - 12)
                else:
                    improvement = 1.0
                    # Slow continuous improvement +0.1-0.3%/month
                    learning = (1 + local_rng.uniform(0.001, 0.003)) ** i

                noise = local_rng.normal(0, 0.005)
                yield_val = base_yield * improvement * learning + noise
                yield_val = float(np.clip(yield_val, 0.50, 0.99))

                # Deliberate imperfection: 0.3% nulls (sensor dropout)
                if local_rng.random() < 0.003:
                    yield_val = None

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

    db_path = get_sqlite_path(
        config["databases"]["raw"]["target_yield"], config
    )

    all_month_keys = get_all_month_keys()
    snapshots = [
        (SNAPSHOT_1_ID, SNAPSHOT_1_DATE),
        (SNAPSHOT_2_ID, SNAPSHOT_2_DATE),
    ]

    all_dfs = []
    for snap_id, snap_date in snapshots:
        logger.info(f"  Generating snapshot: {snap_id}")
        df = generate_yield_for_snapshot(snap_id, snap_date, all_month_keys)
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