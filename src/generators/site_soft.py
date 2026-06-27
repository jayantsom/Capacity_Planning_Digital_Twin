"""
Generator: raw_site_soft.db
Site operational parameters (shifts, working days, allowance, productivity).
Monthly grain — parameters can change over time.
"""

import numpy as np
import pandas as pd

from config.constants import RANDOM_SEED
from src.utils.db_utils import load_config, get_sqlite_path
from src.utils.month_utils import get_all_month_keys, month_key_label
from src.generators.reference_data import write_to_sqlite, SITES
from src.utils.logger import logger


# ── Regional shift profiles ────────────────────────────────────────────────────
# (wd_normal, wd_extended, wd_max,
#  shifts_normal, shifts_mid, shifts_max,
#  hrs_normal, hrs_extended, hrs_max,
#  allowance_pct, productivity_pct)

REGION_PROFILES = {
    "EMEA": (20, 23, 25,  2, 2, 3,  8.0,  9.0, 12.0, 0.12, 0.88),
    "APAC": (22, 25, 27,  2, 3, 3,  8.0, 10.0, 12.0, 0.08, 0.90),
    "AMER": (21, 23, 25,  2, 2, 3,  8.0,  9.0, 12.0, 0.11, 0.87),
    "LATAM":(22, 24, 26,  2, 2, 3,  8.0,  9.0, 10.0, 0.11, 0.85),
    "INDIA": (22, 25, 27, 2, 3, 3,  8.0,  9.0, 12.0, 0.10, 0.86),
}

# Site-specific overrides on top of regional defaults
SITE_OVERRIDES = {
    "FLX_SZN": {"shifts_normal": 3, "shifts_mid": 3, "allowance_pct": 0.07,
                 "productivity_pct": 0.91, "wd_normal": 23, "wd_max": 28},
    "LUX_SZN": {"shifts_normal": 3, "shifts_mid": 3, "allowance_pct": 0.07,
                 "productivity_pct": 0.91, "wd_normal": 23, "wd_max": 28},
    "ERI_MOS": {"wd_max": 24, "shifts_max": 2, "hrs_max": 10.0,
                 "allowance_pct": 0.12, "productivity_pct": 0.84},
    "FLX_HCM": {"wd_normal": 24, "wd_extended": 26, "wd_max": 27},
    "LUX_HNI": {"wd_normal": 24, "wd_extended": 26, "wd_max": 27},
    "JAB_PUN": {"region_override": "INDIA"},
}

# Region lookup per site
SITE_REGION = {s[0]: s[6] for s in SITES}


def _get_site_profile(site_code: str) -> dict:
    override = SITE_OVERRIDES.get(site_code, {})
    region = override.get("region_override", SITE_REGION.get(site_code, "APAC"))
    profile = REGION_PROFILES.get(region, REGION_PROFILES["APAC"])

    (wd_n, wd_e, wd_m,
     sh_n, sh_mid, sh_mx,
     hr_n, hr_e, hr_mx,
     allow, prod) = profile

    result = {
        "wd_normal":     wd_n,   "wd_extended": wd_e, "wd_max": wd_m,
        "shifts_normal": sh_n,   "shifts_mid":  sh_mid, "shifts_max": sh_mx,
        "hrs_normal":    hr_n,   "hrs_extended": hr_e, "hrs_max": hr_mx,
        "allowance_pct": allow,  "productivity_pct": prod,
    }
    result.update({k: v for k, v in override.items()
                   if k != "region_override"})
    return result


def generate_site_soft_db(config: dict) -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("GENERATING: raw_site_soft.db")
    logger.info("=" * 60)

    db_path = get_sqlite_path(
        config["databases"]["raw"]["site_soft"], config
    )

    all_month_keys = get_all_month_keys()
    rows = []

    for site_tuple in SITES:
        site_code = site_tuple[0]
        p = _get_site_profile(site_code)

        seed_val = hash(f"{site_code}|soft") % (2**31)
        local_rng = np.random.default_rng(seed_val)

        soft_row = {"site": site_code}

        for mk in all_month_keys:
            month = mk % 100
            # Slight working day variation by month
            # (public holidays reduce working days in some months)
            wd_adj = 0
            if month in [1, 5, 12]:  # Jan, May, Dec — holiday-heavy
                wd_adj = -1
            elif month in [8, 10]:   # Aug, Oct — standard
                wd_adj = 0

            # Rare shift schedule changes (+1 shift added during demand peaks)
            shift_boost = 1 if (local_rng.random() < 0.05) else 0

            col_prefix = month_key_label(mk)
            soft_row[f"{col_prefix}_wd_normal"]      = max(18, p["wd_normal"] + wd_adj)
            soft_row[f"{col_prefix}_wd_extended"]    = max(20, p["wd_extended"] + wd_adj)
            soft_row[f"{col_prefix}_wd_max"]         = max(22, p["wd_max"] + wd_adj)
            soft_row[f"{col_prefix}_shifts_normal"]  = p["shifts_normal"]
            soft_row[f"{col_prefix}_shifts_mid"]     = min(3, p["shifts_mid"] + shift_boost)
            soft_row[f"{col_prefix}_shifts_max"]     = p["shifts_max"]
            soft_row[f"{col_prefix}_hrs_normal"]     = p["hrs_normal"]
            soft_row[f"{col_prefix}_hrs_extended"]   = p["hrs_extended"]
            soft_row[f"{col_prefix}_hrs_max"]        = p["hrs_max"]
            soft_row[f"{col_prefix}_allowance_pct"]  = round(
                p["allowance_pct"] + local_rng.normal(0, 0.005), 4)
            soft_row[f"{col_prefix}_productivity_pct"] = round(
                float(np.clip(
                    p["productivity_pct"] + local_rng.normal(0, 0.008),
                    0.70, 0.98
                )), 4)

        rows.append(soft_row)

    df = pd.DataFrame(rows)
    write_to_sqlite(df, "site_soft", db_path)

    logger.info(f"  Total rows: {len(df):,} "
                f"(22 sites × {len(all_month_keys)} months — wide format)")
    logger.success("raw_site_soft.db complete")
    return df


if __name__ == "__main__":
    cfg = load_config()
    generate_site_soft_db(cfg)