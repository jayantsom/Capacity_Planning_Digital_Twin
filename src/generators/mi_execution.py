"""
Generator: raw_mi_execution.db
Daily manufacturing execution data from test systems and sensors.
Jan 2023 → Jun 2026 (actual period only — MI is always ACTUAL).
Deliberate imperfections: missing days, null yields, duplicates,
yield excursions, equipment downtime spikes.
"""

import numpy as np
import pandas as pd
from datetime import date, timedelta

from config.constants import RANDOM_SEED
from src.utils.db_utils import load_config, get_sqlite_path
from src.utils.month_utils import date_to_month_key
from src.generators.assignment_matrix import ASSIGNMENT_MATRIX
from src.generators.reference_data import write_to_sqlite, TEST_TYPES
from src.utils.logger import logger


# ── Date range ────────────────────────────────────────────────────────────────
ACTUAL_START = date(2023, 1, 1)
ACTUAL_END   = date(2026, 6, 30)

# ── Base throughput ranges by test type (units/day/site) ──────────────────────
# Derived from: demand / working_days / equipment_qty (approximated)
DAILY_THROUGHPUT_BASE = {
    "OTA": (20,  120),
    "TRX": (40,  300),
    "PIM": (30,  200),
    "PAM": (30,  200),
    "FCT": (100, 800),
    "ICT": (200, 1500),
    "BIT": (50,  400),
    "ALT": (20,  150),
    "UC":  (40,  300),
    "AT":  (50,  400),
}

# Lookup: test_type → (category_id)
TEST_CAT_ID = {t[0]: t[2] for t in TEST_TYPES}

# Factory code lookup
SITE_FACTORY = {}


def _build_site_factory_map() -> dict:
    """Build site_code → factory_code mapping from reference data."""
    from src.generators.reference_data import SITES
    return {s[0]: s[2] for s in SITES}


def _generate_dates(start: date, end: date) -> list[date]:
    """Generate all calendar dates in range."""
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # Saturday=5, Sunday=6


def generate_mi_execution_db(config: dict) -> None:
    logger.info("=" * 60)
    logger.info("GENERATING: raw_mi_execution.db")
    logger.info("=" * 60)

    db_path = get_sqlite_path(
        config["databases"]["raw"]["manufacturing_intelligence"], config
    )

    site_factory = _build_site_factory_map()
    all_dates = _generate_dates(ACTUAL_START, ACTUAL_END)
    total_days = len(all_dates)
    logger.info(f"  Date range: {ACTUAL_START} → {ACTUAL_END} "
                f"({total_days} days)")

    # Process in monthly batches to manage memory
    rows_written = 0
    first_batch = True

    # Group assignments by site for efficient processing
    from collections import defaultdict
    site_assignments = defaultdict(list)
    for a in ASSIGNMENT_MATRIX:
        site_assignments[a["site_code"]].append(a)

    # Monthly batches
    current = ACTUAL_START
    batch_num = 0

    while current <= ACTUAL_END:
        # Determine month end
        if current.month == 12:
            month_end = date(current.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(current.year, current.month + 1, 1) - timedelta(days=1)
        month_end = min(month_end, ACTUAL_END)

        batch_num += 1
        month_label = current.strftime("%Y-%m")
        month_dates = _generate_dates(current, month_end)
        batch_rows = []

        for site_code, assignments in site_assignments.items():
            factory_code = site_factory.get(site_code, f"F{site_code}")

            for assignment in assignments:
                product_num = assignment["product_number"]
                family      = assignment["product_family"]
                status      = assignment["product_status"]
                test_types  = assignment["test_types"]

                for tt in test_types:
                    cat_id = TEST_CAT_ID.get(tt, "999999")

                    # Deterministic RNG per site-product-test-month
                    seed_val = hash(
                        f"{site_code}|{product_num}|{tt}|{month_label}"
                    ) % (2**31)
                    local_rng = np.random.default_rng(seed_val)

                    # Base daily throughput
                    tp_min, tp_max = DAILY_THROUGHPUT_BASE.get(tt, (50, 300))
                    base_throughput = local_rng.uniform(tp_min, tp_max)

                    # NPI: lower throughput until ramp complete
                    if status == "NPI":
                        months_since_2023 = (
                            (current.year - 2023) * 12 + current.month - 1
                        )
                        base_throughput *= min(1.0, months_since_2023 / 18)

                    # Base yield from approximate target
                    from src.generators.target_yield import YIELD_BASE
                    y_min, y_max = YIELD_BASE.get(tt, (0.85, 0.95))
                    base_yield = local_rng.uniform(y_min, y_max)

                    # Yield excursion event: 5% probability per month
                    has_excursion = local_rng.random() < 0.05
                    excursion_start = local_rng.integers(0, max(1, len(month_dates) - 3))
                    excursion_duration = int(local_rng.integers(2, 5))

                    # Equipment downtime event: ~0.5% daily probability
                    downtime_days = set(
                        i for i in range(len(month_dates))
                        if local_rng.random() < 0.005
                    )

                    # Missing day indices: 2% of days have no MI record
                    missing_day_indices = set(
                        i for i in range(len(month_dates))
                        if local_rng.random() < 0.02
                    )

                    # Duplicate record indices: 0.5%
                    duplicate_indices = set(
                        i for i in range(len(month_dates))
                        if local_rng.random() < 0.005
                    )

                    for i, d in enumerate(month_dates):
                        # Skip missing days
                        if i in missing_day_indices:
                            continue

                        # Skip weekends (most sites don't run on weekends
                        # unless extended mode — simplification)
                        if _is_weekend(d):
                            if local_rng.random() > 0.15:
                                continue

                        # Daily throughput variation ±20%
                        daily_qty = max(1, int(
                            base_throughput * local_rng.uniform(0.80, 1.20)
                        ))

                        # Yield: apply excursion if active
                        if has_excursion and (
                            excursion_start <= i < excursion_start + excursion_duration
                        ):
                            day_yield = max(0.50, base_yield - local_rng.uniform(0.08, 0.15))
                        else:
                            day_yield = float(np.clip(
                                base_yield + local_rng.normal(0, 0.02),
                                0.50, 0.99
                            ))

                        # Null yield: 1% sensor dropout
                        if local_rng.random() < 0.01:
                            day_yield = None

                        passed_qty = (
                            int(daily_qty * day_yield)
                            if day_yield is not None
                            else int(daily_qty * base_yield)
                        )
                        failed_qty = daily_qty - passed_qty
                        final_yield = (
                            round(day_yield, 4) if day_yield is not None else None
                        )

                        # Equipment downtime
                        if i in downtime_days:
                            downtime_sec = float(local_rng.uniform(7200, 28800))
                        else:
                            downtime_sec = float(local_rng.uniform(0, 300))

                        # Test duration: base ± 5%, spikes 2%
                        from src.generators.target_test_time import TEST_TIME_BASE
                        tt_min, tt_max = TEST_TIME_BASE.get(tt, (60, 300))
                        base_tt = local_rng.uniform(tt_min, tt_max)
                        if local_rng.random() < 0.02:
                            test_dur = base_tt * local_rng.uniform(1.3, 1.8)
                        else:
                            test_dur = base_tt * local_rng.uniform(0.95, 1.05)

                        row = {
                            "factory_code":           factory_code,
                            "site_code":              site_code,
                            "test_category_id":       cat_id,
                            "test_type":              tt,
                            "product_number":         product_num,
                            "product_type":           "PARENT"
                                                      if assignment.get("is_parent")
                                                      else "CHILD",
                            "execution_date":         d.isoformat(),
                            "month_key":              date_to_month_key(d),
                            "passed_qty":             passed_qty,
                            "failed_qty":             failed_qty,
                            "total_qty":              daily_qty,
                            "yield_avg":              final_yield,
                            "final_test_yield_avg":   final_yield,
                            "test_duration_avg_sec":  round(test_dur, 2),
                            "handling_time_avg_sec":  round(
                                float(local_rng.uniform(10, 120)), 2),
                            "setup_time_avg_sec":     round(
                                float(local_rng.uniform(5, 60)), 2),
                            "load_unload_time_avg_sec": round(
                                float(local_rng.uniform(5, 30)), 2),
                            "idle_time_avg_sec":      round(
                                float(local_rng.uniform(0, 120)), 2),
                            "retest_count_avg":       round(
                                float(local_rng.uniform(0, 0.3)), 3),
                            "equipment_downtime_avg_sec": round(downtime_sec, 2),
                            "actual_throughput_uph":  round(
                                passed_qty / max(0.1,
                                    (test_dur + 30) / 3600), 2),
                        }
                        batch_rows.append(row)

                        # Add duplicate record
                        if i in duplicate_indices:
                            dup = row.copy()
                            batch_rows.append(dup)

        # Write batch to SQLite
        if batch_rows:
            batch_df = pd.DataFrame(batch_rows)
            with __import__("sqlite3").connect(db_path) as conn:
                batch_df.to_sql(
                    "mi_execution", conn,
                    if_exists="replace" if first_batch else "append",
                    index=False
                )
            rows_written += len(batch_rows)
            first_batch = False
            logger.info(f"  Batch {batch_num:02d} ({month_label}): "
                        f"{len(batch_rows):,} rows written "
                        f"[total: {rows_written:,}]")

        current = month_end + timedelta(days=1)

    logger.info(f"  Final total: {rows_written:,} rows")
    logger.success("raw_mi_execution.db complete")