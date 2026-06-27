"""
Generator: raw_reference_data.db
Contains: site_master, test_type_master, equipment_master
No dependencies on other databases.
"""

import hashlib
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from config.constants import RANDOM_SEED
from src.utils.db_utils import load_config, get_sqlite_path
from src.utils.logger import logger


def md5_key(*args) -> str:
    """Generate deterministic MD5 surrogate key from concatenated args."""
    raw = "|".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()


# ── Site Master ────────────────────────────────────────────────────────────────

SITES = [
    # (site_code, site_name, factory_code, supplier, city, country, region, timezone)
    ("ERI_STK", "Ericsson Stockholm",       "FESTK01", "Ericsson",  "Stockholm",        "Sweden",      "EMEA",  "Europe/Stockholm"),
    ("ERI_TAL", "Ericsson Tallinn",         "FETAL01", "Ericsson",  "Tallinn",           "Estonia",     "EMEA",  "Europe/Tallinn"),
    ("ERI_MAD", "Ericsson Madrid",          "FEMAD01", "Ericsson",  "Madrid",            "Spain",       "EMEA",  "Europe/Madrid"),
    ("ERI_GDN", "Ericsson Gdansk",          "FEGDN01", "Ericsson",  "Gdansk",            "Poland",      "EMEA",  "Europe/Warsaw"),
    ("ERI_BUD", "Ericsson Budapest",        "FEBUD01", "Ericsson",  "Budapest",          "Hungary",     "EMEA",  "Europe/Budapest"),
    ("ERI_MOS", "Ericsson Moscow",          "FEMOS01", "Ericsson",  "Moscow",            "Russia",      "EMEA",  "Europe/Moscow"),
    ("JAB_GDL", "Jabil Guadalajara",        "FJGDL01", "Jabil",     "Guadalajara",       "Mexico",      "LATAM", "America/Mexico_City"),
    ("JAB_PUN", "Jabil Pune",               "FJPUN01", "Jabil",     "Pune",              "India",       "APAC",  "Asia/Kolkata"),
    ("JAB_SGP", "Jabil Singapore",          "FJSGP01", "Jabil",     "Singapore",         "Singapore",   "APAC",  "Asia/Singapore"),
    ("JAB_BEL", "Jabil Belo Horizonte",     "FJBEL01", "Jabil",     "Belo Horizonte",    "Brazil",      "LATAM", "America/Sao_Paulo"),
    ("FLX_HCM", "Flex Ho Chi Minh City",    "FFHCM01", "Flex",      "Ho Chi Minh City",  "Vietnam",     "APAC",  "Asia/Ho_Chi_Minh"),
    ("FLX_SZN", "Flex Shenzhen",            "FFSZN01", "Flex",      "Shenzhen",          "China",       "APAC",  "Asia/Shanghai"),
    ("FLX_SAO", "Flex Sao Paulo",           "FFSAO01", "Flex",      "Sao Paulo",         "Brazil",      "LATAM", "America/Sao_Paulo"),
    ("INF_MUN", "Infineon Munich",          "FIMUN01", "Infineon",  "Munich",            "Germany",     "EMEA",  "Europe/Berlin"),
    ("INF_SEO", "Infineon Seoul",           "FISEO01", "Infineon",  "Seoul",             "South Korea", "APAC",  "Asia/Seoul"),
    ("INF_TSE", "Infineon Tokyo",           "FITSE01", "Infineon",  "Tokyo",             "Japan",       "APAC",  "Asia/Tokyo"),
    ("SAN_AUS", "Sanmina Austin",           "FSAUS01", "Sanmina",   "Austin",            "USA",         "AMER",  "America/Chicago"),
    ("SAN_MXC", "Sanmina Mexico City",      "FSMXC01", "Sanmina",   "Mexico City",       "Mexico",      "LATAM", "America/Mexico_City"),
    ("SAN_PEN", "Sanmina Penang",           "FSPEN01", "Sanmina",   "Penang",            "Malaysia",    "APAC",  "Asia/Kuala_Lumpur"),
    ("LUX_SZN", "Luxshare Shenzhen",        "FLSZN01", "Luxshare",  "Shenzhen",          "China",       "APAC",  "Asia/Shanghai"),
    ("LUX_TWN", "Luxshare Taipei",          "FLTWN01", "Luxshare",  "Taipei",            "Taiwan",      "APAC",  "Asia/Taipei"),
    ("LUX_HNI", "Luxshare Hanoi",           "FLHNI01", "Luxshare",  "Hanoi",             "Vietnam",     "APAC",  "Asia/Bangkok"),
]


def generate_site_master() -> pd.DataFrame:
    rows = []
    for s in SITES:
        site_code, site_name, factory_code, supplier, city, country, region, tz = s
        rows.append({
            "site_pk":       md5_key(site_code),
            "site_code":     site_code,
            "site_name":     site_name,
            "factory_code":  factory_code,
            "supplier_name": supplier,
            "city":          city,
            "country":       country,
            "region":        region,
            "timezone":      tz,
            "is_active":     1,
        })
    return pd.DataFrame(rows)


# ── Test Type Master ───────────────────────────────────────────────────────────

TEST_TYPES = [
    # (test_type, category, category_id, category_name, description, responsible, applicable_families)
    ("OTA", "RF Testing",              "110100",
     "Over-The-Air Test",
     "Validates RF radiation pattern, EIRP, and EVM in an anechoic chamber",
     "RF Systems Test Lead",
     "Massive MIMO Radio,Sub-6GHz Radio,mmWave Radio,Active Antenna Unit"),

    ("TRX", "Transceiver Testing",     "120100",
     "Transceiver Performance Test",
     "Measures TX power, RX sensitivity, frequency accuracy, and modulation quality",
     "Transceiver Validation Lead",
     "Massive MIMO Radio,Sub-6GHz Radio,mmWave Radio,Baseband Unit,Digital Unit"),

    ("PIM", "Filter Testing",          "130100",
     "Passive Intermodulation Test",
     "Detects signal distortion caused by nonlinearities in passive components under high power",
     "Filter and Passive Test Lead",
     "RF Filter Module,Duplexer Unit,Active Antenna Unit"),

    ("PAM", "Amplifier Testing",       "140100",
     "Power Amplifier Measurement",
     "Characterizes gain, efficiency, linearity, and harmonic distortion of power amplifiers",
     "Power Amplifier Test Lead",
     "RF Amplifier,Power Amplifier Board,Massive MIMO Radio"),

    ("FCT", "Functional Testing",      "150100",
     "Functional Circuit Test",
     "End-to-end functional verification of PCB assemblies at board level",
     "Functional Test Lead",
     "Baseband Card,Power Supply Unit,Transport Node,Digital Unit"),

    ("ICT", "Circuit Testing",         "150200",
     "In-Circuit Test",
     "Component-level electrical verification using bed-of-nails fixture",
     "In-Circuit Test Lead",
     "Baseband Card,Power Supply Unit,RF Filter Module,Power Amplifier Board"),

    ("BIT", "Reliability Testing",     "160100",
     "Burn-In Test",
     "Early failure screening by operating units at elevated temperature and voltage stress",
     "Reliability Test Lead",
     "Baseband Unit,Power Supply Unit,Digital Unit,Transport Node"),

    ("ALT", "Reliability Testing",     "160200",
     "Accelerated Life Test",
     "Long-duration reliability validation under combined thermal and vibration stress",
     "Accelerated Life Test Lead",
     "Massive MIMO Radio,Baseband Unit,Microwave Link,Power Supply Unit"),

    ("UC",  "Calibration",             "170100",
     "Unit Calibration",
     "Frequency, power, and phase calibration against traceable reference standards",
     "Calibration Lab Lead",
     "Massive MIMO Radio,Sub-6GHz Radio,mmWave Radio,Microwave Link"),

    ("AT",  "Acceptance Testing",      "180100",
     "Acceptance Test",
     "Full functional end-of-line acceptance test per customer specification",
     "Quality Acceptance Lead",
     "Massive MIMO Radio,Sub-6GHz Radio,mmWave Radio,Baseband Unit,Microwave Link,"
     "Millimeter Wave Backhaul,Transport Node,Power Supply Unit"),
]


def generate_test_type_master() -> pd.DataFrame:
    rows = []
    for t in TEST_TYPES:
        tt, cat, cat_id, cat_name, desc, resp, families = t
        rows.append({
            "test_type_pk":       md5_key(tt),
            "test_type":          tt,
            "test_category":      cat,
            "test_category_id":   cat_id,
            "test_category_name": cat_name,
            "test_category_desc": desc,
            "responsible_person": resp,
            "applicable_products": families,
            "is_active":          1,
        })
    return pd.DataFrame(rows)


# ── Equipment Master ───────────────────────────────────────────────────────────

SYSTEMS = [
    # (equip_id, name, family, test_type, manufacturer, model, max_fixture_slots)
    ("OTA-SYS-001", "OTA Anechoic Chamber System A",    "OTA Chamber",         "OTA", "Satimo",    "SG-64",          2),
    ("OTA-SYS-002", "OTA Anechoic Chamber System B",    "OTA Chamber",         "OTA", "Satimo",    "SG-128",         2),
    ("TRX-SYS-001", "Transceiver Test System A",        "TRX Test Rack",       "TRX", "Rohde & Schwarz", "CMX500",   3),
    ("TRX-SYS-002", "Transceiver Test System B",        "TRX Test Rack",       "TRX", "Keysight",  "UXM-5G",         3),
    ("TRX-SYS-003", "Transceiver Test System C",        "TRX Test Rack",       "TRX", "Rohde & Schwarz", "CMX500",   3),
    ("PIM-SYS-001", "PIM Analyzer System A",            "PIM Analyzer",        "PIM", "Anritsu",   "MT8212E",        2),
    ("PAM-SYS-001", "Power Amplifier Test System A",    "PA Test Rack",        "PAM", "Keysight",  "N9030B",         2),
    ("PAM-SYS-002", "Power Amplifier Test System B",    "PA Test Rack",        "PAM", "Rohde & Schwarz", "FSW",      2),
    ("FCT-SYS-001", "Functional Circuit Test System A", "FCT Station",         "FCT", "Teradyne",  "UltraFLEX",      4),
    ("FCT-SYS-002", "Functional Circuit Test System B", "FCT Station",         "FCT", "Teradyne",  "UltraFLEX",      4),
    ("FCT-SYS-003", "Functional Circuit Test System C", "FCT Station",         "FCT", "Advantest", "T2000",          4),
    ("ICT-SYS-001", "In-Circuit Test System A",         "ICT Tester",          "ICT", "Keysight",  "i3070",          2),
    ("ICT-SYS-002", "In-Circuit Test System B",         "ICT Tester",          "ICT", "Teradyne",  "TestStation",    2),
    ("BIT-SYS-001", "Burn-In Oven System A",            "Burn-In Oven",        "BIT", "Despatch",  "LCC-Series",     0),
    ("ALT-SYS-001", "Environmental Chamber System A",   "Environmental Chamber","ALT","Thermotron", "S-Series",      0),
    ("UC-SYS-001",  "RF Calibration System A",          "Calibration Rack",    "UC",  "Keysight",  "E4438C",         1),
    ("UC-SYS-002",  "RF Calibration System B",          "Calibration Rack",    "UC",  "Rohde & Schwarz", "SMW200A",  1),
    ("AT-SYS-001",  "Acceptance Test Station A",        "AT Station",          "AT",  "National Instruments", "PXI", 0),
    ("AT-SYS-002",  "Acceptance Test Station B",        "AT Station",          "AT",  "National Instruments", "PXI", 0),
]

FIXTURES = [
    # (equip_id, name, family, test_type, manufacturer, model, parent_system_id, is_shared)
    ("OTA-FXT-001", "Massive MIMO Antenna Test Fixture",     "Antenna Fixture",    "OTA", "Custom",  "MMF-64T",   "OTA-SYS-001", 0),
    ("OTA-FXT-002", "Sub-6GHz Antenna Test Fixture",         "Antenna Fixture",    "OTA", "Custom",  "S6F-4T",    "OTA-SYS-002", 0),
    ("OTA-FXT-003", "mmWave Antenna Shared Fixture",         "Antenna Fixture",    "OTA", "Custom",  "MWF-28G",   "OTA-SYS-001", 1),
    ("TRX-FXT-001", "Baseband Card TRX Interface Fixture",   "TRX Fixture",        "TRX", "Custom",  "BBTF-5G",   "TRX-SYS-001", 0),
    ("TRX-FXT-002", "Digital Unit TRX Shared Fixture",       "TRX Fixture",        "TRX", "Custom",  "DUTF-G3",   "TRX-SYS-002", 1),
    ("TRX-FXT-003", "Radio Board TRX Interface Fixture",     "TRX Fixture",        "TRX", "Custom",  "RBTF-NR",   "TRX-SYS-003", 0),
    ("PIM-FXT-001", "RF Filter PIM Test Fixture",            "PIM Fixture",        "PIM", "Custom",  "FPIM-B3",   "PIM-SYS-001", 0),
    ("PIM-FXT-002", "High-Power Antenna PIM Fixture",        "PIM Fixture",        "PIM", "Custom",  "HPAF-4T",   "PIM-SYS-001", 0),
    ("PAM-FXT-001", "Power Amplifier Board Shared Fixture",  "PA Fixture",         "PAM", "Custom",  "PABF-35G",  "PAM-SYS-001", 1),
    ("PAM-FXT-002", "RF Amplifier Module Test Fixture",      "PA Fixture",         "PAM", "Custom",  "RAMF-21G",  "PAM-SYS-002", 0),
    ("FCT-FXT-001", "Baseband Board FCT Fixture",            "FCT Fixture",        "FCT", "Custom",  "BBFT-5G",   "FCT-SYS-001", 0),
    ("FCT-FXT-002", "Power Supply Board FCT Fixture",        "FCT Fixture",        "FCT", "Custom",  "PSFT-48V",  "FCT-SYS-002", 0),
    ("FCT-FXT-003", "Radio Board FCT Interface Fixture",     "FCT Fixture",        "FCT", "Custom",  "RBFT-NR",   "FCT-SYS-003", 0),
    ("FCT-FXT-004", "Transport Board FCT Fixture",           "FCT Fixture",        "FCT", "Custom",  "TBFT-FH",   "FCT-SYS-001", 0),
    ("ICT-FXT-001", "Standard PCB Bed-of-Nails Fixture",     "ICT Fixture",        "ICT", "Ingun",   "GKS-100",   "ICT-SYS-001", 1),
    ("ICT-FXT-002", "High-Density PCB ICT Fixture",          "ICT Fixture",        "ICT", "Ingun",   "GKS-200",   "ICT-SYS-002", 0),
    ("UC-FXT-001",  "RF Calibration Reference Fixture",      "Calibration Fixture","UC",  "Keysight","85052D",    "UC-SYS-001",  1),
]


def generate_equipment_master() -> pd.DataFrame:
    rows = []
    for s in SYSTEMS:
        equip_id, name, family, test_type, mfr, model, max_slots = s
        rows.append({
            "equipment_pk":       md5_key(equip_id),
            "equipment_id":       equip_id,
            "equipment_name":     name,
            "equipment_type":     "SYSTEM",
            "equipment_family":   family,
            "test_type":          test_type,
            "manufacturer":       mfr,
            "model_number":       model,
            "parent_system_id":   None,
            "is_shared_fixture":  0,
            "max_fixture_slots":  max_slots,
        })
    for f in FIXTURES:
        equip_id, name, family, test_type, mfr, model, parent_sys, is_shared = f
        rows.append({
            "equipment_pk":       md5_key(equip_id),
            "equipment_id":       equip_id,
            "equipment_name":     name,
            "equipment_type":     "FIXTURE",
            "equipment_family":   family,
            "test_type":          test_type,
            "manufacturer":       mfr,
            "model_number":       model,
            "parent_system_id":   parent_sys,
            "is_shared_fixture":  is_shared,
            "max_fixture_slots":  0,
        })
    return pd.DataFrame(rows)


# ── Writer ─────────────────────────────────────────────────────────────────────

def write_to_sqlite(df: pd.DataFrame, table_name: str, db_path: Path) -> None:
    """Write DataFrame to SQLite table, replacing if exists."""
    with sqlite3.connect(db_path) as conn:
        df.to_sql(table_name, conn, if_exists="replace", index=False)
    logger.info(f"  Written {len(df):>6,} rows → {table_name} ({db_path.name})")


def generate_reference_data(config: dict) -> None:
    """Master function: generate all reference data and write to SQLite."""
    logger.info("=" * 60)
    logger.info("GENERATING: raw_reference_data.db")
    logger.info("=" * 60)

    db_path = get_sqlite_path(
        config["databases"]["raw"]["reference_data"], config
    )

    site_df = generate_site_master()
    write_to_sqlite(site_df, "site_master", db_path)
    logger.info(f"  Sites: {len(site_df)} records")

    test_type_df = generate_test_type_master()
    write_to_sqlite(test_type_df, "test_type_master", db_path)
    logger.info(f"  Test types: {len(test_type_df)} records")

    equip_df = generate_equipment_master()
    write_to_sqlite(equip_df, "equipment_master", db_path)
    logger.info(f"  Equipment: {len(equip_df)} records "
                f"({len(SYSTEMS)} systems, {len(FIXTURES)} fixtures)")

    logger.success("raw_reference_data.db complete")
    return site_df, test_type_df, equip_df


if __name__ == "__main__":
    cfg = load_config()
    generate_reference_data(cfg)