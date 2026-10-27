"""
Generator: raw_target_test_time.db
Monthly target test time (seconds) per site-product-test_type combination.
"""

from datetime import date

import numpy as np
import pandas as pd

from capacity_twin_core.dates.months import get_all_month_keys, month_key_label
from capacity_twin_core.domain.constants import (
    FORECAST_SOURCE_PLANNER,
    RANDOM_SEED,
)
from capacity_twin_core.logging import logger
from capacity_twin_core.runtime.database_paths import get_sqlite_path, load_config
from data_operations.generator.generators.assignment_matrix import (
    ASSIGNMENT_MATRIX,
)
from data_operations.generator.generators.reference_data import TEST_TYPES, write_to_sqlite
from data_operations.generator.rules.contracts import DateContract
from data_operations.generator.rules.determinism import stable_seed
from data_operations.generator.rules.npi import npi_ramp
from data_operations.generator.services.control_catalog import load_assignments

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


def generate_test_time_for_planning_version(
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
            seed_val = stable_seed(
                root_seed, site_code, product_num, tt, "target-test-time"
            )
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
                "planning_version_id":        planning_version_id,
                "plan_as_of_date":      plan_as_of_date,
                "forecast_source":    FORECAST_SOURCE_PLANNER,
            }

            for i, mk in enumerate(all_month_keys):
                month_date = date(mk // 100, mk % 100, 1)
                if status == "NPI" and npi_ramp(product_num, month_date) == 0:
                    time_row[month_key_label(mk)] = None
                    continue
                # Continuous improvement: -0.5%/month for OLD products
                if status == "OLD":
                    improvement = (1 - 0.005) ** i
                else:
                    # NPI: penalty shrinks over 12 months then improves
                    ramp = npi_ramp(product_num, month_date)
                    npi_factor = 1.0 + (npi_initial_penalty - 1.0) * (1.0 - ramp)
                    improvement = npi_factor

                # Monthly noise ±3%
                noise = local_rng.uniform(0.97, 1.03)
                test_time = base_time * improvement * noise

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

    dates = DateContract.from_config(config)
    planning_versions = [
        (f"plan-{plan_as_of_date.isoformat()}", plan_as_of_date.isoformat())
        for plan_as_of_date in dates.plan_as_of_dates
    ]
    assignments = load_assignments(config)

    all_dfs = []
    for planning_version_id, plan_as_of_date in planning_versions:
        logger.info(f"  Generating planning version: {planning_version_id}")
        df = generate_test_time_for_planning_version(
            planning_version_id,
            plan_as_of_date,
            all_month_keys,
            int(config["data_generation"]["random_seed"]),
            assignments,
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