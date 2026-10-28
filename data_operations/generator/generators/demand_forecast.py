"""
Generator: raw_demand_forecast.db
Horizontal monthly demand forecast for all site-product pairs.
Covers Jan 2023 → Dec 2027 (60 months) with 2 planning versions.
"""

import numpy as np
import pandas as pd

from capacity_twin_core.dates.months import get_all_month_keys, month_key_label
from capacity_twin_core.domain.constants import (
    FORECAST_SOURCE_PLANNER,
    RANDOM_SEED,
)
from capacity_twin_core.logging import logger
from capacity_twin_core.runtime.database_paths import get_sqlite_path, load_config
from data_operations.generator.catalogs.contract_tables import (
    build_product_bom,
    build_site_product_sources,
)
from data_operations.generator.generators.assignment_matrix import ASSIGNMENT_MATRIX
from data_operations.generator.generators.reference_data import write_to_sqlite
from data_operations.generator.rules.contracts import DateContract
from data_operations.generator.rules.determinism import stable_seed
from data_operations.generator.services.control_catalog import load_assignments
from data_operations.generator.services.demand_reconciliation import build_demand_requirements

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
    "ERV_STK": 1.4, "ERV_TAL": 0.7, "ERV_MAD": 0.9, "ERV_GDN": 0.8,
    "ERV_BUD": 0.8, "ERV_MOS": 0.6, "JAB_GDL": 1.0, "JAB_PUN": 1.1,
    "JAB_SGP": 1.3, "JAB_BEL": 0.6, "FLX_HCM": 0.9, "FLX_SZN": 1.4,
    "FLX_SAO": 0.7, "INF_MUN": 1.0, "INF_SEO": 1.1, "INF_TSE": 0.9,
    "SAN_AUS": 0.8, "SAN_MXC": 0.7, "SAN_PEN": 1.0, "LUX_SZN": 1.2,
    "LUX_TWN": 1.0, "LUX_HNI": 0.8,
}


def _seasonality_factor(mk: int, amplitude: float, q4_peak: bool) -> float:
    """Sinusoidal seasonality peaking in November (month 11)."""
    month = mk % 100
    if q4_peak:
        # Peak at month 11, trough at month 4
        angle = (month - 11) * (2 * np.pi / 12)
        return 1.0 + amplitude * np.cos(angle)
    return 1.0


def _planning_version_noise(
    root_seed: int,
    business_key: tuple[str, str],
    mk: int,
    planning_version_id: str,
    plan_as_of_date: str,
) -> float:
    """
    Forecast planning versions diverge from actuals.
    The earlier version is a rougher long-range estimate.
    The later version is more refined and closer to actuals.
    """
    plan_as_of_month = int(plan_as_of_date[:4]) * 100 + int(plan_as_of_date[5:7])
    if mk <= plan_as_of_month:
        return 1.0
    months_ahead = (mk // 100 - plan_as_of_month // 100) * 12 + (mk % 100 - plan_as_of_month % 100)
    months_ahead = max(0, months_ahead)
    std = 0.03 + 0.008 * months_ahead
    rng = np.random.default_rng(
        stable_seed(root_seed, *business_key, planning_version_id, mk, "forecast-error")
    )
    return max(0.5, rng.normal(1.0, std))


def generate_demand_for_planning_version(
    planning_version_id: str,
    plan_as_of_date: str,
    all_month_keys: list[int],
    rng: np.random.Generator,
    root_seed: int = RANDOM_SEED,
    assignments: list[dict] | None = None,
) -> pd.DataFrame:
    rows = []

    for assignment in assignments or ASSIGNMENT_MATRIX:
        site_code   = assignment["site_code"]
        product_num = assignment["product_number"]
        family      = assignment["product_family"]

        profile = DEMAND_PROFILES.get(family, (200, 1000, 0.002, 0.08, False))
        base_min, base_max, trend_mo, seas_amp, q4_peak = profile

        site_factor = SITE_SIZE_FACTORS.get(site_code, 1.0)

        # Deterministic base demand per site-product
        # Excluding planning version keeps all already-known actuals immutable.
        seed_val = stable_seed(root_seed, site_code, product_num, "demand")
        local_rng = np.random.default_rng(seed_val)
        base_demand = local_rng.uniform(base_min, base_max) * site_factor

        demand_row = {
            "site":               site_code,
            "product_platform":   assignment["platform"],
            "product_family":     family,
            "product_number":     product_num,
            "planning_version_id":        planning_version_id,
            "plan_as_of_date":      plan_as_of_date,
            "forecast_source":    FORECAST_SOURCE_PLANNER,
        }

        for i, mk in enumerate(all_month_keys):
            # Trend factor: compound monthly growth from Jan 2023
            trend = (1 + trend_mo) ** i
            # Seasonality
            seas = _seasonality_factor(mk, seas_amp, q4_peak)
            # Forecast planning version noise (FORECAST months only)
            planning_version_noise = _planning_version_noise(
                root_seed,
                (site_code, product_num),
                mk,
                planning_version_id,
                plan_as_of_date,
            )
            # Unit noise ±15%
            noise = local_rng.uniform(0.85, 1.15)

            raw_demand = base_demand * trend * seas * planning_version_noise * noise

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

    db_path = get_sqlite_path(config["databases"]["raw"]["demand"], config)

    date_contract = DateContract.from_config(config)
    all_month_keys = get_all_month_keys(
        date_contract.actual_start, date_contract.forecast_end
    )
    root_seed = int(config["data_generation"]["random_seed"])
    rng = np.random.default_rng(root_seed)
    planning_versions = [
        (f"plan-{plan_as_of_date.isoformat()}", plan_as_of_date.isoformat())
        for plan_as_of_date in date_contract.plan_as_of_dates
    ]
    assignments = load_assignments(config)

    all_dfs = []
    for planning_version_id, plan_as_of_date in planning_versions:
        logger.info(f"  Generating planning version: {planning_version_id}")
        df = generate_demand_for_planning_version(
            planning_version_id, plan_as_of_date, all_month_keys, rng
            , root_seed, assignments
        )
        all_dfs.append(df)
        logger.info(f"    Rows: {len(df):,}")

    combined = pd.concat(all_dfs, ignore_index=True)

    # Convert the internal wide frame into the explicit demand contract.
    independent_rows = []
    for record in combined.to_dict("records"):
        for month_key in all_month_keys:
            independent_rows.append(
                {
                    "planning_version_id": record["planning_version_id"],
                    "plan_as_of_date": record["plan_as_of_date"],
                    "month_key": month_key,
                    "site": record["site"],
                    "product_number": record["product_number"],
                    "quantity": record[month_key_label(month_key)] or 0,
                    "knowledge_type": (
                        "ACTUAL"
                        if month_key <= int(record["plan_as_of_date"][:4]) * 100
                        + int(record["plan_as_of_date"][5:7])
                        else "FORECAST"
                    ),
                }
            )
    demand_requirements = build_demand_requirements(
        pd.DataFrame(independent_rows),
        build_product_bom(),
        build_site_product_sources(assignments),
    )
    write_to_sqlite(demand_requirements, "demand_requirement", db_path)

    logger.info(f"  Total rows: {len(combined):,} "
                f"({len(all_month_keys)} months × "
                f"{len(assignments)} assignments × "
                f"{len(planning_versions)} planning versions)")
    logger.success("raw_demand_forecast.db complete")
    return combined


if __name__ == "__main__":
    cfg = load_config()
    generate_demand_forecast_db(cfg)