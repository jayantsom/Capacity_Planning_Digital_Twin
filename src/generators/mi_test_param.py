"""
Generator: raw_mi_test_param.db
Daily test × parameter data derived from MI execution records.
"""

import sqlite3
import numpy as np
import pandas as pd
from datetime import date, timedelta

from config.constants import RANDOM_SEED
from src.utils.db_utils import load_config, get_sqlite_path
from src.utils.month_utils import date_to_month_key
from src.generators.assignment_matrix import ASSIGNMENT_MATRIX
from src.generators.reference_data import write_to_sqlite, TEST_TYPES, SITES
from src.generators.target_yield import YIELD_BASE
from src.utils.logger import logger

ACTUAL_START = date(2023, 1, 1)
ACTUAL_END   = date(2026, 6, 30)

TEST_CAT_ID = {t[0]: t[2] for t in TEST_TYPES}
SITE_FACTORY = {s[0]: s[2] for s in SITES}

# Retest quote by test type (Test × Parameter)
RETEST_QUOTE = {
    "OTA": 0.75, "TRX": 0.75, "PIM": 0.70,
    "PAM": 0.75, "FCT": 0.75, "ICT": 0.75,
    "BIT": 0.70, "ALT": 0.70, "UC": 0.75, "AT": 0.75,
}


def generate_mi_test_param_db(config: dict) -> None:
    logger.info("=" * 60)
    logger.info("GENERATING: raw_mi_test_param.db")
    logger.info("=" * 60)

    db_path = get_sqlite_path(
        config["databases"]["raw"]["test_x_parameter"], config
    )

    from collections import defaultdict
    site_assignments = defaultdict(list)
    for a in ASSIGNMENT_MATRIX:
        site_assignments[a["site_code"]].append(a)

    rows_written = 0
    first_batch = True
    current = ACTUAL_START

    while current <= ACTUAL_END:
        if current.month == 12:
            month_end = date(current.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(current.year, current.month + 1, 1) - timedelta(days=1)
        month_end = min(month_end, ACTUAL_END)

        month_label = current.strftime("%Y-%m")
        month_dates = []
        d = current
        while d <= month_end:
            month_dates.append(d)
            d += timedelta(days=1)

        batch_rows = []

        for site_code, assignments in site_assignments.items():
            factory_code = SITE_FACTORY.get(site_code, site_code)

            for assignment in assignments:
                product_num = assignment["product_number"]
                test_types  = assignment["test_types"]

                for tt in test_types:
                    cat_id = TEST_CAT_ID.get(tt, "999999")
                    retest_quote = RETEST_QUOTE.get(tt, 0.75)

                    seed_val = hash(
                        f"{site_code}|{product_num}|{tt}|param|{month_label}"
                    ) % (2**31)
                    local_rng = np.random.default_rng(seed_val)

                    y_min, y_max = YIELD_BASE.get(tt, (0.85, 0.95))
                    base_yield = local_rng.uniform(y_min, y_max)

                    # Yield retest values
                    yield_retest1   = float(np.clip(
                        local_rng.uniform(0.70, 0.90), 0.50, 0.99))
                    yield_retest2   = float(np.clip(
                        local_rng.uniform(0.85, 0.98), 0.50, 0.99))

                    # Type 2 retest times formula
                    retest_times_t2 = (
                        (1 - yield_retest1 + yield_retest2) / yield_retest2
                    )

                    for i, d in enumerate(month_dates):
                        if d.weekday() >= 5 and local_rng.random() > 0.15:
                            continue
                        if local_rng.random() < 0.02:
                            continue

                        total_qty = max(1, int(local_rng.uniform(50, 500)))
                        fp_yield  = float(np.clip(
                            base_yield + local_rng.normal(0, 0.02),
                            0.50, 0.99
                        ))
                        fp_qty    = int(total_qty * fp_yield)
                        ff_qty    = total_qty - fp_qty

                        batch_rows.append({
                            "factory_code":       factory_code,
                            "site_code":          site_code,
                            "product_number":     product_num,
                            "test_category_id":   cat_id,
                            "test_type":          tt,
                            "execution_date":     d.isoformat(),
                            "month_key":          date_to_month_key(d),
                            "first_pass_qty":     fp_qty,
                            "first_fail_qty":     ff_qty,
                            "total_qty":          total_qty,
                            "first_pass_yield":   round(fp_yield, 4),
                            "test_x_parameter":   retest_quote,
                            "retest_times_avg":   round(
                                float(local_rng.uniform(1.5, 2.5)), 3),
                            "retest_times_type1": 2.0,
                            "retest_times_type2": round(retest_times_t2, 4),
                            "yield_retest_1":     round(yield_retest1, 4),
                            "yield_retest_2_plus":round(yield_retest2, 4),
                        })

        if batch_rows:
            batch_df = pd.DataFrame(batch_rows)
            with sqlite3.connect(db_path) as conn:
                batch_df.to_sql(
                    "mi_test_param", conn,
                    if_exists="replace" if first_batch else "append",
                    index=False
                )
            rows_written += len(batch_rows)
            first_batch = False
            logger.info(f"  {month_label}: {len(batch_rows):,} rows "
                        f"[total: {rows_written:,}]")

        current = month_end + timedelta(days=1)

    logger.info(f"  Final total: {rows_written:,} rows")
    logger.success("raw_mi_test_param.db complete")