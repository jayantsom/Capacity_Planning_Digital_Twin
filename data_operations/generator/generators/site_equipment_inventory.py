"""
Generator: raw_site_equip_inv.db
Monthly equipment inventory per site-test_type combination.
Equipment quantities change over time: additions on demand growth,
retirements, and maintenance months.
"""

from collections import defaultdict

import numpy as np
import pandas as pd

from capacity_twin_core.dates.months import get_all_month_keys, month_key_label
from capacity_twin_core.domain.constants import RANDOM_SEED
from capacity_twin_core.logging import logger
from capacity_twin_core.runtime.database_paths import get_sqlite_path, load_config
from data_operations.generator.catalogs.contract_tables import (
    build_resource_contracts,
    build_routes,
)
from data_operations.generator.generators.assignment_matrix import ASSIGNMENT_MATRIX
from data_operations.generator.generators.reference_data import FIXTURES, SYSTEMS, write_to_sqlite
from data_operations.generator.rules.determinism import stable_seed

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
    "SPI": (8, 20, 0.80, 0.94, 1, 8, 0.82, 0.94, 0.93, 0.98, 0.75, 3000, 9000),
    "AOI": (10, 25, 0.80, 0.94, 1, 8, 0.82, 0.94, 0.93, 0.98, 0.75, 3000, 9000),
    "AXI": (20, 45, 0.75, 0.90, 1, 5, 0.78, 0.92, 0.91, 0.97, 0.75, 2500, 7000),
    "JTAG": (15, 40, 0.80, 0.94, 1, 10, 0.80, 0.94, 0.92, 0.98, 0.75, 3000, 9000),
    "FWP": (10, 30, 0.82, 0.95, 1, 12, 0.84, 0.95, 0.94, 0.99, 0.75, 4000, 10000),
    "CRF": (30, 75, 0.75, 0.91, 1, 8, 0.76, 0.91, 0.91, 0.97, 0.75, 2000, 7000),
    "MIMO": (60, 120, 0.72, 0.89, 1, 6, 0.74, 0.90, 0.90, 0.97, 0.75, 1500, 6000),
    "MWP": (45, 100, 0.74, 0.90, 1, 6, 0.75, 0.90, 0.90, 0.97, 0.75, 1800, 6000),
    "ETH": (20, 60, 0.80, 0.94, 1, 12, 0.82, 0.94, 0.93, 0.98, 0.75, 3500, 10000),
    "SER": (30, 75, 0.78, 0.92, 1, 8, 0.80, 0.93, 0.92, 0.98, 0.75, 3000, 9000),
    "OPT": (30, 90, 0.76, 0.91, 1, 10, 0.78, 0.92, 0.92, 0.98, 0.75, 2500, 8000),
    "TIM": (20, 60, 0.80, 0.93, 1, 8, 0.81, 0.93, 0.93, 0.98, 0.75, 3000, 9000),
    "PWR": (20, 60, 0.80, 0.93, 1, 10, 0.82, 0.94, 0.93, 0.98, 0.75, 3000, 9000),
    "ENV": (90, 120, 0.65, 0.86, 1, 5, 0.75, 0.90, 0.90, 0.97, 0.70, 800, 3000),
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

    # Build exactly the qualified inventory relationships accepted by preflight.
    contracts = build_resource_contracts()
    route_df, route_step_df = build_routes()
    product_by_route = dict(
        zip(route_df["route_id"], route_df["product_number"], strict=True)
    )
    behavior_by_product_test = {
        (product_by_route[row["route_id"]], row["test_type"]): row["capacity_behavior"]
        for row in route_step_df.to_dict("records")
    }
    compatibility = defaultdict(list)
    for row in contracts["tester_fixture_compatibility"].to_dict("records"):
        compatibility[row["tester_resource_id"]].append(row["fixture_resource_id"])
    resource_type = {
        row["resource_id"]: (
            "SYSTEM" if row["resource_kind"] == "TEST_SYSTEM" else row["resource_kind"]
        )
        for row in contracts["resource_master"].to_dict("records")
    }
    inventory_by_site_test = defaultdict(set)
    for row in contracts["product_resource_qualification"].to_dict("records"):
        site_test = (row["site_code"], row["test_type"])
        inventory_by_site_test[site_test].add(row["resource_id"])
        if (
            behavior_by_product_test[(row["product_number"], row["test_type"])]
            == "PAIRED_FIXTURE"
        ):
            inventory_by_site_test[site_test].update(compatibility[row["resource_id"]])

    for site_code, test_type in sorted(site_test_pairs):
        params = EQUIP_PARAMS.get(test_type)
        if params is None:
            continue

        (ht_min, ht_max, util_min, util_max,
         qty_min, qty_max,
         ry1_min, ry1_max, ry2_min, ry2_max,
         retest_quote, ttbf_min, ttbf_max) = params

        families = sorted(site_family_map[(site_code, test_type)])

        equipment_list = [
            (resource_id, resource_type[resource_id])
            for resource_id in sorted(inventory_by_site_test[(site_code, test_type)])
        ]

        if not equipment_list:
            continue

        for equip_id, equip_type in equipment_list:
            seed_val = stable_seed(RANDOM_SEED, site_code, test_type, equip_id)
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
                "resource_pool_id":   f"POOL-{test_type}",
                "data_provenance":    "SYNTHETIC_SITE_RESOURCE_ASSIGNMENT",
            }

            for i, mk in enumerate(all_month_keys):
                # Equipment additions when demand grows significantly
                if i > 0 and i % 6 == 0 and local_rng.random() < 0.25:
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
    fixtures_count = len([r for r in rows if r["equipment_type"] != "SYSTEM"])
    logger.info(f"  Total rows: {len(df):,} "
                f"({systems_count} system rows, {fixtures_count} fixture rows)")
    logger.success("raw_site_equip_inv.db complete")
    return df


if __name__ == "__main__":
    cfg = load_config()
    generate_site_equipment_inventory_db(cfg)