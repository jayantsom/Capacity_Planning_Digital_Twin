"""
Generator: raw_machine_logs.db
Error, warning, and info logs derived from Machine execution events.
Generated from the same random seeds as Machine execution so log events
are consistent with the execution data imperfections.
"""

import sqlite3
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from capacity_twin_core.dates.months import date_to_month_key
from capacity_twin_core.logging import logger
from capacity_twin_core.runtime.database_paths import get_sqlite_path
from data_operations.generator.generators.assignment_matrix import ASSIGNMENT_MATRIX
from data_operations.generator.generators.reference_data import SITES, TEST_TYPES
from data_operations.generator.rules.contracts import DateContract
from data_operations.generator.rules.determinism import stable_seed
from data_operations.generator.services.operational_derivation import derive_logs

TEST_CAT_ID = {t[0]: t[2] for t in TEST_TYPES}
SITE_FACTORY = {s[0]: s[2] for s in SITES}

# ── Error code catalog ─────────────────────────────────────────────────────────
ERROR_CATALOG = {
    # (code, description, severity, trigger_probability)
    "E-001": ("Yield Excursion Below Threshold", "ERROR", 0.05),
    "E-002": ("Equipment Downtime Event Detected", "ERROR", 0.005),
    "E-003": ("Test Duration Anomaly Detected", "ERROR", 0.02),
    "E-004": ("Sensor Data Missing or Invalid", "ERROR", 0.01),
    "E-005": ("Complete Batch Failure — Zero Pass", "CRITICAL", 0.003),
    "E-006": ("Retest Limit Exceeded", "CRITICAL", 0.002),
    "W-001": ("Yield Trending Down — 3-Day Moving Average", "WARN", 0.08),
    "W-002": ("Test Time Increasing Trend Detected", "WARN", 0.04),
    "W-003": ("Equipment Utilization Above 95%", "WARN", 0.03),
    "I-001": ("Planned Maintenance Scheduled", "INFO", 0.015),
    "I-002": ("NPI Product First Article Inspection", "INFO", 0.01),
    "C-001": ("Equipment Calibration Due", "INFO", 0.012),
}


def generate_machine_logs_db(config: dict) -> None:
    logger.info("=" * 60)
    logger.info("GENERATING: raw_machine_logs.db")
    logger.info("=" * 60)

    db_path = get_sqlite_path(config["databases"]["raw"]["machine"], config)
    execution_path = get_sqlite_path(config["databases"]["raw"]["execution"], config)
    dates = DateContract.from_config(config)
    actual_start = dates.actual_start
    actual_end = dates.actual_end
    rows_written = derive_logs(execution_path, db_path)
    logger.info(f"  Final total: {rows_written:,} rows")
    logger.success("raw_machine_logs.db complete")
    return

    from collections import defaultdict

    site_assignments = defaultdict(list)
    for a in ASSIGNMENT_MATRIX:
        site_assignments[a["site_code"]].append(a)

    rows_written = 0
    first_batch = True
    current = actual_start

    while current <= actual_end:
        if current.month == 12:
            month_end = date(current.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(current.year, current.month + 1, 1) - timedelta(days=1)
        month_end = min(month_end, actual_end)

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
                status = assignment["product_status"]
                test_types = assignment["test_types"]

                for tt in test_types:
                    cat_id = TEST_CAT_ID.get(tt, "999999")

                    seed_val = stable_seed(
                        config["data_generation"]["random_seed"],
                        site_code,
                        product_num,
                        tt,
                        "logs",
                        month_label,
                    )
                    local_rng = np.random.default_rng(seed_val)

                    for d in month_dates:
                        if d.weekday() >= 5 and local_rng.random() > 0.15:
                            continue

                        for error_code, (desc, severity, prob) in ERROR_CATALOG.items():
                            # NPI products: higher probability of INFO logs
                            adjusted_prob = prob
                            if status == "NPI" and error_code == "I-002":
                                adjusted_prob = 0.05
                            if status == "NPI" and error_code.startswith("E"):
                                adjusted_prob *= 1.5

                            if local_rng.random() < adjusted_prob:
                                # 5% of records have unknown description
                                final_desc = "Unknown" if local_rng.random() < 0.05 else desc

                                # Random hour for log timestamp
                                log_hour = int(local_rng.integers(6, 22))
                                log_min = int(local_rng.integers(0, 59))
                                log_ts = datetime(
                                    d.year, d.month, d.day, log_hour, log_min
                                ).isoformat()

                                batch_rows.append(
                                    {
                                        "factory_code": factory_code,
                                        "site_code": site_code,
                                        "product_number": product_num,
                                        "test_category_id": cat_id,
                                        "test_type": tt,
                                        "error_code": error_code,
                                        "error_description": final_desc,
                                        "severity": severity,
                                        "log_ts": log_ts,
                                        "execution_date": d.isoformat(),
                                        "month_key": date_to_month_key(d),
                                    }
                                )

        if batch_rows:
            batch_df = pd.DataFrame(batch_rows)
            with sqlite3.connect(db_path) as conn:
                batch_df.to_sql(
                    "machine_logs",
                    conn,
                    if_exists="replace" if first_batch else "append",
                    index=False,
                )
            rows_written += len(batch_rows)
            first_batch = False
            logger.info(f"  {month_label}: {len(batch_rows):,} log rows [total: {rows_written:,}]")

        current = month_end + timedelta(days=1)

    logger.info(f"  Final total: {rows_written:,} rows")
    logger.success("raw_machine_logs.db complete")
