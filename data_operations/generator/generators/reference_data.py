"""
Generator: raw_reference_data.db
Contains: site_master, test_type_master, equipment_master
No dependencies on other databases.
"""

import hashlib
import sqlite3
from pathlib import Path

import pandas as pd

from capacity_twin_core.logging import logger
from capacity_twin_core.runtime.database_paths import get_sqlite_path, load_config


def md5_key(*args) -> str:
    """Generate deterministic MD5 surrogate key from concatenated args."""
    raw = "|".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()


# ── Site Master ────────────────────────────────────────────────────────────────

SYNTHETIC_DISCLAIMER = (
    "Synthetic educational data. Real manufacturer names are reference data only; "
    "capabilities, products, volumes, routes, and performance imply no affiliation."
)

SITES = [
    # (site_code, site_name, factory_code, supplier, city, country, region, timezone)
    ("ERV_STK", "Erivon Stockholm",          "FEVSTK01", "Erivon",   "Stockholm",         "Sweden",      "EMEA",  "Europe/Stockholm"),
    ("ERV_TAL", "Erivon Tallinn",            "FEVTAL01", "Erivon",   "Tallinn",           "Estonia",     "EMEA",  "Europe/Tallinn"),
    ("ERV_MAD", "Erivon Madrid",             "FEVMAD01", "Erivon",   "Madrid",            "Spain",       "EMEA",  "Europe/Madrid"),
    ("ERV_GDN", "Erivon Gdansk",             "FEVGDN01", "Erivon",   "Gdansk",            "Poland",      "EMEA",  "Europe/Warsaw"),
    ("ERV_BUD", "Erivon Budapest",           "FEVBUD01", "Erivon",   "Budapest",          "Hungary",     "EMEA",  "Europe/Budapest"),
    ("ERV_MOS", "Erivon Moscow",             "FEVMOS01", "Erivon",   "Moscow",            "Russia",      "EMEA",  "Europe/Moscow"),
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
    ("CEL_MTY", "Celestica Monterrey",       "FCMTY01", "Celestica","Monterrey",         "Mexico",      "AMER",  "America/Monterrey"),
    ("CEL_ORD", "Celestica Oradea",          "FCORD01", "Celestica","Oradea",            "Romania",     "EMEA",  "Europe/Bucharest"),
    ("CEL_JHR", "Celestica Johor",           "FCJHR01", "Celestica","Johor",             "Malaysia",    "APAC",  "Asia/Kuala_Lumpur"),
    ("BCH_ALM", "Benchmark Almelo",          "FBALM01", "Benchmark","Almelo",            "Netherlands", "EMEA",  "Europe/Amsterdam"),
    ("JEM_CEN", "Jemstech Centurion",        "FJCEN01", "Jemstech", "Centurion",         "South Africa","AFRICA","Africa/Johannesburg"),
    ("GPC_SYD", "GPC Sydney",                "FGSYD01", "GPC",      "Sydney",             "Australia",   "OCEANIA","Australia/Sydney"),
    ("NAU_AKL", "Nautech Auckland",          "FNAKL01", "Nautech",  "Auckland",           "New Zealand", "OCEANIA","Pacific/Auckland"),
    ("FLX_MAO", "Flex Manaus",               "FFMAO01", "Flex",     "Manaus",             "Brazil",      "LATAM", "America/Manaus"),
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
            "data_provenance": "PUBLIC_LOCATION_SYNTHETIC_CAPABILITY",
            "synthetic_disclaimer": SYNTHETIC_DISCLAIMER,
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
     ("Massive MIMO Radio,Sub-6GHz Radio,mmWave Radio,Baseband Unit,Microwave Link,"
      "Millimeter Wave Backhaul,Transport Node,Power Supply Unit")),

    # Expanded route-driven manufacturing tests. They are not applied globally.
    ("SPI", "PCBA Inspection", "210100", "Solder Paste Inspection",
     "Checks solder-paste volume and placement before reflow", "PCBA Quality Lead",
     "Baseband Card,Power Supply Board,Optical Line Card"),
    ("AOI", "PCBA Inspection", "210200", "Automated Optical Inspection",
     "Checks visible placement and solder defects", "PCBA Quality Lead",
     "Baseband Card,Power Supply Board,Optical Line Card"),
    ("AXI", "PCBA Inspection", "210300", "Automated X-ray Inspection",
     "Checks hidden solder joints and dense packages", "PCBA Quality Lead",
     "Baseband Card,RF Amplifier,Optical Line Card"),
    ("JTAG", "Circuit Testing", "220100", "Boundary Scan and JTAG",
     "Checks digital interconnect and programmable devices", "Digital Test Lead",
     "Baseband Card,Digital Unit,Enterprise Switch"),
    ("FWP", "Programming", "220200", "Firmware Programming",
     "Loads and verifies approved synthetic firmware images", "Programming Lead",
     "Digital Unit,Router,Enterprise Switch,Optical Access"),
    ("CRF", "RF Testing", "230100", "Conducted RF Test",
     "Measures conducted RF performance without OTA radiation", "RF Test Lead",
     "Massive MIMO Radio,Sub-6GHz Radio,Microwave Link"),
    ("MIMO", "RF Calibration", "230200", "Beamforming and MIMO Calibration",
     "Calibrates phase and amplitude paths across channels", "RF Calibration Lead",
     "Massive MIMO Radio,Active Antenna Unit"),
    ("MWP", "Microwave Testing", "230300", "Microwave Performance Test",
     "Measures microwave and E-band path performance", "Microwave Test Lead",
     "Microwave Link,Millimeter Wave Backhaul"),
    ("ETH", "Network Testing", "240100", "Ethernet Traffic Test",
     "Synthetic RFC 2544 and Y.1564-oriented traffic checks", "Network Test Lead",
     "Router,Enterprise Switch,Transport Node"),
    ("SER", "High Speed Digital", "240200", "High-Speed SerDes Test",
     "Measures high-speed electrical lane quality", "Digital Signal Integrity Lead",
     "Router,Enterprise Switch,Optical Line Card"),
    ("OPT", "Optical Testing", "240300", "Optical Power Eye and BER Test",
     "Measures optical power, wavelength, eye quality, and BER", "Optical Test Lead",
     "Optical Transport,Optical Line Card,Optical Pluggable,Optical Access"),
    ("TIM", "Timing", "240400", "PTP and SyncE Timing Test",
     "Checks packet and frequency synchronization behavior", "Timing Test Lead",
     "Router,Transport Node,Digital Unit"),
    ("PWR", "Power and Safety", "250100", "PoE and Power Load Test",
     "Checks input, output, PoE, and synthetic load behavior", "Power Test Lead",
     "Power Supply Unit,Enterprise Switch,Wireless Access"),
    ("ENV", "Environmental", "250200", "Thermal Cycling and ESS",
     "Screens units under bounded synthetic thermal stress", "Reliability Test Lead",
     "Massive MIMO Radio,Router,Optical Transport,Wireless Access"),
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
    ("SPI-SYS-001", "Solder Paste Inspection Cell",     "SPI Cell",            "SPI", "Koh Young", "Synthetic-SPI", 1),
    ("AOI-SYS-001", "Automated Optical Inspection Cell","AOI Cell",            "AOI", "Omron", "Synthetic-AOI", 2),
    ("AXI-SYS-001", "Automated X-ray Inspection Cell",  "AXI Cell",            "AXI", "Nordson", "Synthetic-AXI", 1),
    ("JTG-SYS-001", "Boundary Scan Test Rack",           "JTAG Rack",           "JTAG","Keysight", "Synthetic-JTAG", 4),
    ("FWP-SYS-001", "Firmware Programming Cell",         "Programming Cell",    "FWP", "Data I/O", "Synthetic-FWP", 8),
    ("CRF-SYS-001", "Conducted RF Test Rack",            "RF Test Rack",        "CRF", "Rohde & Schwarz", "Synthetic-CRF", 4),
    ("MIM-SYS-001", "MIMO Calibration Rack",             "MIMO Calibration",    "MIMO","LitePoint", "Synthetic-MIMO", 8),
    ("MWP-SYS-001", "Microwave Performance Rack",        "Microwave Rack",      "MWP", "Anritsu", "Synthetic-MWP", 2),
    ("ETH-SYS-001", "Ethernet Traffic Test Rack",        "Network Test Rack",   "ETH", "VIAVI", "Synthetic-ETH", 8),
    ("SER-SYS-001", "High-Speed SerDes Test Rack",       "SerDes Rack",         "SER", "Keysight", "Synthetic-SER", 4),
    ("OPT-SYS-001", "Optical Production Test Rack",      "Optical Test Rack",   "OPT", "EXFO", "Synthetic-OPT", 8),
    ("TIM-SYS-001", "Packet Timing Test Rack",           "Timing Rack",         "TIM", "VIAVI", "Synthetic-TIM", 4),
    ("PWR-SYS-001", "Power and PoE Load Rack",           "Power Load Rack",     "PWR", "Chroma", "Synthetic-PWR", 8),
    ("ENV-SYS-001", "Thermal ESS Chamber",               "Environmental Chamber","ENV","ESPEC", "Synthetic-ENV", 16),
    ("CRF-SYS-002", "Alternate Conducted RF Rack",       "RF Test Rack",        "CRF", "Keysight", "Synthetic-CRF-ALT", 4),
    ("MIM-SYS-002", "Alternate MIMO Calibration Rack",   "MIMO Calibration",    "MIMO","Rohde & Schwarz", "Synthetic-MIMO-ALT", 8),
    ("ETH-SYS-002", "Alternate Ethernet Traffic Rack",   "Network Test Rack",   "ETH", "EXFO", "Synthetic-ETH-ALT", 8),
    ("OPT-SYS-002", "Alternate Optical Test Rack",       "Optical Test Rack",   "OPT", "Keysight", "Synthetic-OPT-ALT", 8),
    ("ICT-SYS-003", "Flying Probe and ICT Cell",         "ICT Tester",          "ICT", "SPEA", "Synthetic-FP-ICT", 4),
    ("PWR-SYS-002", "Alternate Power Safety Rack",       "Power Load Rack",     "PWR", "Chroma", "Synthetic-PWR-ALT", 8),
    ("ENV-SYS-002", "Shared Thermal Chamber",            "Environmental Chamber","ENV","Thermotron", "Synthetic-ENV-ALT", 16),
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

# Expanded tests receive one passive carrier on their primary system. Three
# active fixtures are separate stations and must never be paired to a tester.
for test_code in (
    "SPI", "AOI", "AXI", "JTAG", "FWP", "CRF", "MIMO",
    "MWP", "ETH", "SER", "OPT", "TIM", "PWR", "ENV",
):
    primary_system = next(system[0] for system in SYSTEMS if system[3] == test_code)
    FIXTURES.append(
        (
            f"{test_code}-FXT-001",
            f"{test_code} Passive Product Carrier",
            f"{test_code} Fixture",
            test_code,
            "Custom",
            f"SYN-{test_code}-PASSIVE",
            primary_system,
            1,
        )
    )
for test_code in ("FCT", "FWP", "PWR"):
    FIXTURES.append(
        (
            f"{test_code}-ACT-001",
            f"{test_code} Active Standalone Station",
            f"{test_code} Active Fixture",
            test_code,
            "Custom",
            f"SYN-{test_code}-ACTIVE",
            None,
            0,
        )
    )


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
            "data_provenance":    "PUBLIC_VENDOR_SYNTHETIC_CONFIGURATION",
            "synthetic_disclaimer": SYNTHETIC_DISCLAIMER,
        })
    for f in FIXTURES:
        equip_id, name, family, test_type, mfr, model, parent_sys, is_shared = f
        rows.append({
            "equipment_pk":       md5_key(equip_id),
            "equipment_id":       equip_id,
            "equipment_name":     name,
            "equipment_type":     "ACTIVE_FIXTURE" if parent_sys is None else "FIXTURE",
            "equipment_family":   family,
            "test_type":          test_type,
            "manufacturer":       mfr,
            "model_number":       model,
            "parent_system_id":   parent_sys,
            "is_shared_fixture":  is_shared,
            "max_fixture_slots":  0,
            "data_provenance":    "SYNTHETIC_CUSTOM_FIXTURE",
            "synthetic_disclaimer": SYNTHETIC_DISCLAIMER,
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

    site_db = get_sqlite_path(config["databases"]["raw"]["site"], config)
    test_db = get_sqlite_path(config["databases"]["raw"]["test"], config)
    machine_db = get_sqlite_path(config["databases"]["raw"]["machine"], config)
    product_db = get_sqlite_path(config["databases"]["raw"]["product"], config)

    site_df = generate_site_master()
    write_to_sqlite(site_df, "site_master", site_db)
    logger.info(f"  Sites: {len(site_df)} records")

    test_type_df = generate_test_type_master()
    write_to_sqlite(test_type_df, "test_type_master", test_db)
    logger.info(f"  Test types: {len(test_type_df)} records")

    equip_df = generate_equipment_master()
    write_to_sqlite(equip_df, "equipment_master", machine_db)
    logger.info(f"  Equipment: {len(equip_df)} records "
                f"({len(SYSTEMS)} systems, {len(FIXTURES)} fixtures)")

    # Manufacturer names simulate a source-owned equipment master attribute.
    from data_operations.generator.catalogs.contract_tables import (
        CATALOG_VERSION,
    )
    from data_operations.generator.catalogs.contract_tables import (
        SYNTHETIC_DISCLAIMER as CONTRACT_DISCLAIMER,
    )

    manufacturers = (
        equip_df[["manufacturer"]]
        .drop_duplicates()
        .sort_values("manufacturer")
        .assign(
            catalog_version=CATALOG_VERSION,
            reference_use="EDUCATIONAL_EQUIPMENT_CATEGORY",
            synthetic_disclaimer=CONTRACT_DISCLAIMER,
        )
    )
    write_to_sqlite(manufacturers, "manufacturer_master", product_db)

    logger.success("raw_reference_data.db complete")
    return site_df, test_type_df, equip_df


if __name__ == "__main__":
    cfg = load_config()
    generate_reference_data(cfg)