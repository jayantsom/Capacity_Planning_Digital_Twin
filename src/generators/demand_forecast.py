"""
Generator: raw_demand_forecast.db
Horizontal monthly demand forecast for all site-product pairs.
Covers Jan 2023 → Dec 2027 (60 months) with 2 planning snapshots.
"""

import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

from config.constants import (
    RANDOM_SEED, SNAPSHOT_1_ID, SNAPSHOT_2_ID,
    SNAPSHOT_1_DATE, SNAPSHOT_2_DATE,
    DATA_TYPE_ACTUAL, DATA_TYPE_FORECAST,
    FORECAST_SOURCE_PLANNER,
)
from src.utils.db_utils import load_config, get_sqlite_path
from src.utils.month_utils import (
    get_all_month_keys, month_key_label, is_actual
)
from src.generators.assignment_matrix import ASSIGNMENT_MATRIX
from src.generators.reference_data import write_to_sqlite, md5_key
from src.utils.logger import logger


# ── Demand profile per product family ─────────────────────────────────────────

DEMAND_PROFILES = {
    # (base_min, base_max, trend_monthly_pct, seasonality_amplitude, q4_peak)
    "Massive MIMO Radio":       (800,  3000, -0.001, 0.15, True),
    "Sub-6GHz Radio":           (1500, 4000,  0.004, 0.10, True),
    "mmWave Radio":             (50,   400,   0.022, 0.08, True),
    "Active Antenna Unit":      (600,  2500,  0.002, 0.12, True),
    "Baseband Unit":            (300,  1200,  0.003, 0.10, True),
    "Digital Unit":             (200,  800,   0.003, 0.08, False),
    "Baseband Card":            (1000, 4000,  0.003, 0.10, True),
    "Microwave Link":           (100,  600,   0.001, 0.06, False),
    "Millimeter Wave Backhaul": (80,   350,   0.018, 0.07, True),
    "Transport Node":           (150,  700,   0.002, 0.08, False),
    "RF Filter Module":         (2000, 5000,  0.004, 0.10, True),
    "RF Amplifier":             (1500, 4500,  0.004, 0.09, True),
    "Duplexer Unit":            (1200, 3500,  0.003, 0.08, True),
    "Power Supply Unit":        (400,  1500,  0.003, 0.07, False),
    "Power Supply Board":       (800,  3000,  0.003, 0.07, False),
    "Power Amplifier Board":    (600,  2000,  0.004, 0.08, True),
    "Remote Electrical Tilt":   (200,  800,   0.001, 0.05, False),
}

# Site size factor — scales base demand up or down
SITE_SIZE_FACTORS = {
    "ERI_STK": 1.4, "ERI_TAL": 0.7, "ERI_MAD": 0.9, "ERI_GDN": 0.8,
    "ERI_BUD": 0.8, "ERI_MOS": 0.6, "JAB_GDL": 1.0, "JAB_PUN": 1.1,
    "JAB_SGP": 1.3, "JAB_BEL": 0.6, "FLX_HCM": 0.9, "FLX_SZN": 1.4,
    "FLX_SAO": 0.7, "INF_MUN": 1.0, "INF_SEO": 1.1, "INF_TSE": 0.9,
    "SAN_AUS": 0.8, "SAN_MXC": 0.7, "SAN_PEN": 1.0, "LUX_SZN": 1.2,
    "LUX_TWN": 1.0, "LUX_HNI": 0.8,
}


def _npi_ramp_factor(product_number: str, mk: int) -> float:
    """
    NPI products ramp from 0 to full demand over 12 months.
    Returns a multiplier [0.0 → 1.0].
    """
    NPI_START = {
        "RAN-AAU-35128-004": 202407,
        "RAN-MWR-3900-009":  202501,
        "BBP-BBU-6GPR-013":  202504,
        "BBP-DPU-G4-015":    202507,
        "MWT-DBU-150G-021":  202510,
        "RFC-TFL-S6G-026":   202601,
        "RFC-DUP-WB-030":    202504,
        "PWR-PAB-28G-034":   202507,
    }
    start = NPI_START.get(product_number)
    if start is None or mk < start:
        return 0.0
    months_since_start = (mk // 100 - start // 100) * 12 + (mk % 100 - start % 100)
    return min(1.0, months_since_start / 12.0)


def _seasonality_factor(mk: int, amplitude: float, q4_peak: bool) -> float:
    """Sinusoidal seasonality peaking in November (month 11)."""
    month = mk % 100
    if q4_peak:
        # Peak at month 11, trough at month 4
        angle = (month - 11) * (2 * np.pi / 12)
        return 1.0 + amplitude * np.cos(angle)
    return 1.0


def _snapshot_noise(rng: np.random.Generator, mk: int,
                    snapshot_id: str) -> float:
    """
    Forecast snapshots diverge from actuals.
    snap_1 (Jan 2023): rougher long-range estimate.
    snap_2 (Jan 2024): more refined, closer to actuals.
    """
    if is_actual(mk):
        return 1.0  # Actuals are the same in both snapshots
    months_ahead = (mk // 100 - 202607 // 100) * 12 + (mk % 100 - 7)
    months_ahead = max(0, months_ahead)
    if snapshot_id == SNAPSHOT_1_ID:
        std = 0.05 + 0.015 * months_ahead   # grows with horizon
    else:
        std = 0.03 + 0.008 * months_ahead   # tighter
    return max(0.5, rng.normal(1.0, std))


def generate_demand_for_snapshot(
    snapshot_id: str,
    snapshot_date: str,
    all_month_keys: list[int],
    rng: np.random.Generator,
) -> pd.DataFrame:
    rows = []

    for assignment in ASSIGNMENT_MATRIX:
        site_code   = assignment["site_code"]
        product_num = assignment["product_number"]
        family      = assignment["product_family"]
        status      = assignment["product_status"]

        profile = DEMAND_PROFILES.get(family, (200, 1000, 0.002, 0.08, False))
        base_min, base_max, trend_mo, seas_amp, q4_peak = profile

        site_factor = SITE_SIZE_FACTORS.get(site_code, 1.0)

        # Deterministic base demand per site-product
        seed_val = hash(f"{site_code}|{product_num}|{snapshot_id}") % (2**31)
        local_rng = np.random.default_rng(seed_val)
        base_demand = local_rng.uniform(base_min, base_max) * site_factor

        demand_row = {
            "site":               site_code,
            "product_platform":   assignment["platform"],
            "product_family":     family,
            "product_number":     product_num,
            "product_status":     status,
            "snapshot_id":        snapshot_id,
            "snapshot_date":      snapshot_date,
            "forecast_source":    FORECAST_SOURCE_PLANNER,
        }

        for i, mk in enumerate(all_month_keys):
            # Trend factor: compound monthly growth from Jan 2023
            trend = (1 + trend_mo) ** i
            # Seasonality
            seas = _seasonality_factor(mk, seas_amp, q4_peak)
            # NPI ramp
            npi_factor = _npi_ramp_factor(product_num, mk) if status == "NPI" else 1.0
            # Forecast snapshot noise (FORECAST months only)
            snap_noise = _snapshot_noise(rng, mk, snapshot_id)
            # Unit noise ±15%
            noise = local_rng.uniform(0.85, 1.15)

            raw_demand = base_demand * trend * seas * npi_factor * snap_noise * noise

            # Deliberate imperfection: 0.5% null demand
            if local_rng.random() < 0.005 and is_actual(mk):
                raw_demand = None

            col = month_key_label(mk)
            demand_row[col] = (
                None if raw_demand is None
                else int(np.clip(round(raw_demand), 0, 5000))
            )

        rows.append(demand_row)

    return pd.DataFrame(rows)


def generate_demand_forecast_db(config: dict) -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("GENERATING: raw_demand_forecast.db")
    logger.info("=" * 60)

    db_path = get_sqlite_path(
        config["databases"]["raw"]["demand_forecast"], config
    )

    all_month_keys = get_all_month_keys()
    rng = np.random.default_rng(RANDOM_SEED)

    snapshots = [
        (SNAPSHOT_1_ID, SNAPSHOT_1_DATE),
        (SNAPSHOT_2_ID, SNAPSHOT_2_DATE),
    ]

    all_dfs = []
    for snap_id, snap_date in snapshots:
        logger.info(f"  Generating snapshot: {snap_id}")
        df = generate_demand_for_snapshot(
            snap_id, snap_date, all_month_keys, rng
        )
        all_dfs.append(df)
        logger.info(f"    Rows: {len(df):,}")

    combined = pd.concat(all_dfs, ignore_index=True)
    write_to_sqlite(combined, "demand_forecast", db_path)

    logger.info(f"  Total rows: {len(combined):,} "
                f"({len(all_month_keys)} months × "
                f"{len(ASSIGNMENT_MATRIX)} assignments × 2 snapshots)")
    logger.success("raw_demand_forecast.db complete")
    return combined


if __name__ == "__main__":
    cfg = load_config()
    generate_demand_forecast_db(cfg)