"""
Generator: raw_target_test_time.db
Monthly target test time (seconds) per site-product-test_type combination.
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
from src.generators.assignment_matrix import (
    ASSIGNMENT_MATRIX, get_test_types_for_family
)
from src.generators.reference_data import (
    write_to_sqlite, md5_key, TEST_TYPES
)
from src.utils.logger import logger


# ── Base test time ranges by test type (seconds) ──────────────────────────────
TEST_TIME_BASE = {
    "ICT": (30,   120),
    "FCT": (60,   300),
    "UC":  (120,  600),
    "TRX": (180,  900),
    "OTA": (300,  1800),
    "PIM": (180,  720),
    "PAM": (120,  480),
    "BIT": (1800, 3000),
    "ALT": (2400, 3000),
    "AT":  (300,  900),
}

# Lookup: test_type → (category_id, responsible_person)
TEST_TYPE_META = {
    t[0]: (t[2], t[5]) for t in TEST_TYPES
}

# Lookup: test_type → platform context for responsible person
PLATFORM_TEST_RESPONSIBLE = {
    ("Radio Access (RAN)",        "OTA"): "RF Systems Test Lead - RAN",
    ("Baseband and Processing",   "FCT"): "Functional Test Lead - BBP",
    ("RF Components and Filters", "PIM"): "Filter and Passive Test Lead - RFC",
    ("Power and Infrastructure",  "ICT"): "In-Circuit Test Lead - PWR",
}


def generate_test_time_for_snapshot(
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

        for tt in test_types:
            base_min, base_max = TEST_TIME_BASE.get(tt, (60, 300))
            cat_id, responsible = TEST_TYPE_META.get(tt, ("999999", "Unknown"))

            # Override responsible with platform-specific if available
            responsible = PLATFORM_TEST_RESPONSIBLE.get(
                (platform, tt), responsible
            )

            # Deterministic base per site-product-test_type
            seed_val = hash(
                f"{site_code}|{product_num}|{tt}|{snapshot_id}"
            ) % (2**31)
            local_rng = np.random.default_rng(seed_val)

            base_time = local_rng.uniform(base_min, base_max)

            # Site variation ±10%
            site_factor = local_rng.uniform(0.90, 1.10)
            base_time *= site_factor

            # NPI: +20% test time (first 12 months, then normalises)
            npi_initial_penalty = 1.20 if status == "NPI" else 1.0

            time_row = {
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
                # Continuous improvement: -0.5%/month for OLD products
                if status == "OLD":
                    improvement = (1 - 0.005) ** i
                else:
                    # NPI: penalty shrinks over 12 months then improves
                    npi_months = min(i, 12)
                    npi_factor = npi_initial_penalty - (
                        (npi_initial_penalty - 1.0) * npi_months / 12
                    )
                    improvement = npi_factor * (1 - 0.003) ** max(0, i - 12)

                # Monthly noise ±3%
                noise = local_rng.uniform(0.97, 1.03)
                test_time = base_time * improvement * noise

                # Deliberate imperfection: 0.5% nulls
                if local_rng.random() < 0.005:
                    test_time = None

                col = month_key_label(mk)
                time_row[col] = (
                    None if test_time is None
                    else round(float(np.clip(test_time, 5, 3000)), 2)
                )

            rows.append(time_row)

    return pd.DataFrame(rows)


def generate_target_test_time_db(config: dict) -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("GENERATING: raw_target_test_time.db")
    logger.info("=" * 60)

    db_path = get_sqlite_path(
        config["databases"]["raw"]["target_test_time"], config
    )

    all_month_keys = get_all_month_keys()

    snapshots = [
        (SNAPSHOT_1_ID, SNAPSHOT_1_DATE),
        (SNAPSHOT_2_ID, SNAPSHOT_2_DATE),
    ]

    all_dfs = []
    for snap_id, snap_date in snapshots:
        logger.info(f"  Generating snapshot: {snap_id}")
        df = generate_test_time_for_snapshot(
            snap_id, snap_date, all_month_keys
        )
        all_dfs.append(df)
        logger.info(f"    Rows: {len(df):,}")

    combined = pd.concat(all_dfs, ignore_index=True)
    write_to_sqlite(combined, "target_test_time", db_path)

    logger.info(f"  Total rows: {len(combined):,}")
    logger.success("raw_target_test_time.db complete")
    return combined


if __name__ == "__main__":
    cfg = load_config()
    generate_target_test_time_db(cfg)