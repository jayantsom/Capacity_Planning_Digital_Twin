"""
Generator: raw_site_equip_inv.db
Monthly equipment inventory per site-test_type combination.
Equipment quantities change over time: additions on demand growth,
retirements, and maintenance months.
"""

import numpy as np
import pandas as pd
from collections import defaultdict

from config.constants import RANDOM_SEED
from src.utils.db_utils import load_config, get_sqlite_path
from src.utils.month_utils import get_all_month_keys, month_key_label
from src.generators.assignment_matrix import ASSIGNMENT_MATRIX
from src.generators.reference_data import (
    write_to_sqlite, SYSTEMS, FIXTURES
)
from src.utils.logger import logger


# ── Equipment parameters by test type ─────────────────────────────────────────
EQUIP_PARAMS = {
    # test_type: (handling_time_min, handling_time_max,
    #             utilization_min, utilization_max,
    #             base_qty_min, base_qty_max,
    #             retest_yield1_min, retest_yield1_max,
    #             retest_yield2_min, retest_yield2_max,
    #             retest_quote, ttbf_hr_min, ttbf_hr_max)
    "OTA": (90, 120, 0.75, 0.90, 1,  8,  0.72, 0.88, 0.88, 0.96, 0.75, 1000, 4000),
    "TRX": (45, 90,  0.78, 0.92, 2,  15, 0.75, 0.90, 0.90, 0.97, 0.75, 2000, 6000),
    "PIM": (60, 90,  0.76, 0.90, 1,  8,  0.70, 0.85, 0.88, 0.95, 0.70, 1500, 5000),
    "PAM": (45, 75,  0.77, 0.91, 1,  10, 0.73, 0.88, 0.89, 0.96, 0.75, 2000, 6000),
    "FCT": (20, 45,  0.80, 0.92, 5,  40, 0.80, 0.92, 0.92, 0.98, 0.75, 3000, 8000),
    "ICT": (10, 30,  0.82, 0.94, 10, 80, 0.82, 0.94, 0.93, 0.98, 0.75, 4000, 10000),
    "BIT": (60, 120, 0.70, 0.88, 2,  20, 0.78, 0.92, 0.91, 0.97, 0.70, 500,  2000),
    "ALT": (90, 120, 0.65, 0.85, 1,  8,  0.75, 0.90, 0.90, 0.96, 0.70, 500,  1500),
    "UC":  (30, 60,  0.75, 0.90, 1,  10, 0.78, 0.92, 0.92, 0.97, 0.75, 2000, 6000),
    "AT":  (60, 90,  0.78, 0.91, 2,  15, 0.80, 0.92, 0.92, 0.97, 0.75, 2000, 6000),
}

# Build system and fixture lookups by test_type
SYSTEMS_BY_TYPE = defaultdict(list)
for s in SYSTEMS:
    SYSTEMS_BY_TYPE[s[3]].append(s[0])  # test_type → [equip_id]

FIXTURES_BY_TYPE = defaultdict(list)
for f in FIXTURES:
    FIXTURES_BY_TYPE[f[3]].append(f[0])


def generate_site_equipment_inventory_db(config: dict) -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("GENERATING: raw_site_equip_inv.db")
    logger.info("=" * 60)

    db_path = get_sqlite_path(
        config["databases"]["raw"]["site_equipment_inventory"], config
    )

    all_month_keys = get_all_month_keys()
    rows = []

    # Get unique site-test_type combinations from assignment matrix
    site_test_pairs = set()
    site_family_map = defaultdict(set)
    for a in ASSIGNMENT_MATRIX:
        for tt in a["test_types"]:
            site_test_pairs.add((a["site_code"], tt))
            site_family_map[(a["site_code"], tt)].add(a["product_family"])

    for site_code, test_type in sorted(site_test_pairs):
        params = EQUIP_PARAMS.get(test_type)
        if params is None:
            continue

        (ht_min, ht_max, util_min, util_max,
         qty_min, qty_max,
         ry1_min, ry1_max, ry2_min, ry2_max,
         retest_quote, ttbf_min, ttbf_max) = params

        families = list(site_family_map[(site_code, test_type)])

        # All equipment (systems + fixtures) for this test type
        equipment_list = (
            [(eid, "SYSTEM") for eid in SYSTEMS_BY_TYPE[test_type]] +
            [(eid, "FIXTURE") for eid in FIXTURES_BY_TYPE[test_type]]
        )

        if not equipment_list:
            continue

        for equip_id, equip_type in equipment_list:
            seed_val = hash(
                f"{site_code}|{test_type}|{equip_id}"
            ) % (2**31)
            local_rng = np.random.default_rng(seed_val)

            # Base parameters for this site-equipment combo
            handling_time  = round(local_rng.uniform(ht_min, ht_max), 1)
            util_rate      = round(local_rng.uniform(util_min, util_max), 3)
            yield_retest1  = round(local_rng.uniform(ry1_min, ry1_max), 3)
            yield_retest2  = round(local_rng.uniform(ry2_min, ry2_max), 3)
            cycle_time     = round(local_rng.uniform(5, 30), 1)
            qual_time      = round(local_rng.uniform(10, 60), 1)
            ttbf           = round(local_rng.uniform(ttbf_min, ttbf_max), 1)
            repair_tester  = int(local_rng.random() < 0.3)
            is_npi         = int(local_rng.random() < 0.6)
            base_qty       = int(local_rng.integers(qty_min, qty_max + 1))

            # Monthly equipment quantity with realistic changes
            current_qty = base_qty
            # Track maintenance months (1-2 per year)
            maint_months = set(
                local_rng.choice(range(len(all_month_keys)),
                                 size=min(5, len(all_month_keys)//8),
                                 replace=False)
            )

            inv_row = {
                "site":               site_code,
                "platform":           families[0] if families else "Unknown",
                "family":             ", ".join(families[:3]),
                "station":            f"STATION-{site_code}-{test_type}",
                "cabinet":            f"CAB-{equip_id[:3]}-{site_code[-3:]}",
                "test_type":          test_type,
                "test_equipment_id":  equip_id,
                "test_equipment_desc": f"{test_type} {equip_type.title()} at {site_code}",
                "equipment_type":     equip_type,
                "handling_time_sec":  handling_time,
                "qualification_time_sec": qual_time,
                "cycle_time_sec":     cycle_time,
                "utilization_rate":   util_rate,
                "yield_retest_1":     yield_retest1,
                "yield_retest_2_plus":yield_retest2,
                "test_time_before_failure_hr": ttbf,
                "retest_quote":       retest_quote,
                "repair_tester":      repair_tester,
                "is_npi_capable":     is_npi,
            }

            for i, mk in enumerate(all_month_keys):
                # Equipment additions when demand grows significantly
                if i > 0 and i % 6 == 0:
                    if local_rng.random() < 0.25:
                        current_qty += int(local_rng.integers(1, 4))

                # Rare retirements after 36 months of low utilization
                if i > 36 and local_rng.random() < 0.01:
                    current_qty = max(qty_min, current_qty - 1)

                # Maintenance months: qty drops by 1 temporarily
                qty = (
                    max(1, current_qty - 1)
                    if i in maint_months
                    else current_qty
                )

                col = month_key_label(mk)
                inv_row[col] = qty

            rows.append(inv_row)

    df = pd.DataFrame(rows)
    write_to_sqlite(df, "site_equipment_inventory", db_path)

    systems_count = len([r for r in rows if r["equipment_type"] == "SYSTEM"])
    fixtures_count = len([r for r in rows if r["equipment_type"] == "FIXTURE"])
    logger.info(f"  Total rows: {len(df):,} "
                f"({systems_count} system rows, {fixtures_count} fixture rows)")
    logger.success("raw_site_equip_inv.db complete")
    return df


if __name__ == "__main__":
    cfg = load_config()
    generate_site_equipment_inventory_db(cfg)