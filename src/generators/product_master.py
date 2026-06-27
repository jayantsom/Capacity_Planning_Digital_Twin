"""
Generator: raw_product_master.db
Contains: product_master (with parent-child columns)
Depends on: nothing (self-contained catalog)
"""

import sqlite3
from pathlib import Path

import pandas as pd

from src.utils.db_utils import load_config, get_sqlite_path
from src.utils.logger import logger
from src.generators.reference_data import write_to_sqlite, md5_key


# ── Product Catalog ────────────────────────────────────────────────────────────
# (product_number, description, product_type, family, platform, poc, status,
#  child1_pn, child1_qty, child2_pn, child2_qty, child3_pn, child3_qty)

PRODUCTS = [
    # ── Platform 1: Radio Access (RAN) ─────────────────────────────────────
    ("RAN-AAU-3564-001", "64T64R Active Antenna Unit 3.5GHz",
     "Active Antenna Unit", "Massive MIMO Radio", "Radio Access (RAN)",
     "RAN Product Manager", "OLD",
     "BBP-BPC-MM-017", 2, "RFC-LNA-35G-027", 4, "PWR-PAB-35G-033", 2),

    ("RAN-AAU-3532-002", "32T32R Active Antenna Unit 3.5GHz",
     "Active Antenna Unit", "Massive MIMO Radio", "Radio Access (RAN)",
     "RAN Product Manager", "OLD",
     "BBP-BPC-MM-017", 1, "RFC-LNA-35G-027", 2, "PWR-PAB-35G-033", 1),

    ("RAN-AAU-2664-003", "64T64R Active Antenna Unit 2.6GHz",
     "Active Antenna Unit", "Massive MIMO Radio", "Radio Access (RAN)",
     "RAN Product Manager", "OLD",
     "BBP-BPC-MM-017", 2, "RFC-LNA-35G-027", 4, None, None),

    ("RAN-AAU-35128-004", "128T128R Active Antenna Unit 3.5GHz 6G-Ready",
     "Active Antenna Unit", "Massive MIMO Radio", "Radio Access (RAN)",
     "NPI Program Manager", "NPI",
     "BBP-BPC-MM-017", 4, "RFC-LNA-35G-027", 8, "PWR-PAB-35G-033", 4),

    ("RAN-RRU-1844-005", "Remote Radio Unit 1.8GHz 4T4R",
     "Remote Radio Unit", "Sub-6GHz Radio", "Radio Access (RAN)",
     "RAN Product Manager", "OLD",
     "RFC-DPX-B3-024", 1, "RFC-LNA-35G-027", 2, None, None),

    ("RAN-RRU-2144-006", "Remote Radio Unit 2.1GHz 4T4R",
     "Remote Radio Unit", "Sub-6GHz Radio", "Radio Access (RAN)",
     "RAN Product Manager", "OLD",
     "RFC-FLT-B78-025", 1, "RFC-LNA-35G-027", 2, None, None),

    ("RAN-RRU-7022-007", "Remote Radio Unit 700MHz 2T2R",
     "Remote Radio Unit", "Sub-6GHz Radio", "Radio Access (RAN)",
     "RAN Product Manager", "OLD",
     None, None, None, None, None, None),

    ("RAN-MWR-2800-008", "mmWave Radio Unit 28GHz",
     "mmWave Radio Unit", "mmWave Radio", "Radio Access (RAN)",
     "mmWave Product Manager", "OLD",
     "RFC-DUP-B1-029", 2, "PWR-PAB-35G-033", 1, None, None),

    ("RAN-MWR-3900-009", "mmWave Radio Unit 39GHz",
     "mmWave Radio Unit", "mmWave Radio", "Radio Access (RAN)",
     "NPI Program Manager", "NPI",
     "RFC-DUP-WB-030", 2, "PWR-PAB-28G-034", 1, None, None),

    ("RAN-IAA-3532-010", "Integrated Active Antenna 3.5GHz 32T",
     "Integrated Active Antenna", "Active Antenna Unit", "Radio Access (RAN)",
     "RAN Product Manager", "OLD",
     "BBP-BPC-5G-016", 1, "RFC-LNA-35G-027", 2, None, None),

    # ── Platform 2: Baseband & Processing ──────────────────────────────────
    ("BBP-BBU-5GNR-011", "Baseband Unit 5G NR Indoor",
     "Baseband Unit", "Baseband Unit", "Baseband and Processing",
     "Baseband Product Manager", "OLD",
     "BBP-BPC-5G-016", 2, "PWR-PSU-48V-031", 1, None, None),

    ("BBP-BBU-5GNO-012", "Baseband Unit 5G NR Outdoor",
     "Baseband Unit", "Baseband Unit", "Baseband and Processing",
     "Baseband Product Manager", "OLD",
     "BBP-BPC-5G-016", 2, "PWR-PSU-48V-031", 1, None, None),

    ("BBP-BBU-6GPR-013", "Baseband Unit 6G Prototype",
     "Baseband Unit", "Baseband Unit", "Baseband and Processing",
     "NPI Program Manager", "NPI",
     "BBP-BPC-MM-017", 2, "PWR-PSU-48V-031", 1, None, None),

    ("BBP-DPU-G3-014", "Digital Processing Unit Gen3",
     "Digital Unit", "Digital Unit", "Baseband and Processing",
     "Baseband Product Manager", "OLD",
     "BBP-BPC-5G-016", 4, None, None, None, None),

    ("BBP-DPU-G4-015", "Digital Processing Unit Gen4",
     "Digital Unit", "Digital Unit", "Baseband and Processing",
     "NPI Program Manager", "NPI",
     "BBP-BPC-MM-017", 4, None, None, None, None),

    ("BBP-BPC-5G-016", "5G Baseband Processing Card",
     "Baseband Card", "Baseband Card", "Baseband and Processing",
     "Baseband Product Manager", "OLD",
     None, None, None, None, None, None),

    ("BBP-BPC-MM-017", "Massive MIMO Baseband Card",
     "Baseband Card", "Baseband Card", "Baseband and Processing",
     "Baseband Product Manager", "OLD",
     None, None, None, None, None, None),

    # ── Platform 3: Microwave & Transport ──────────────────────────────────
    ("MWT-MLU-15G-018", "Microwave Link Unit 15GHz",
     "Microwave Link", "Microwave Link", "Microwave and Transport",
     "Transport Product Manager", "OLD",
     "RFC-DUP-B1-029", 1, "PWR-PSU-48V-031", 1, None, None),

    ("MWT-MLU-23G-019", "Microwave Link Unit 23GHz",
     "Microwave Link", "Microwave Link", "Microwave and Transport",
     "Transport Product Manager", "OLD",
     None, None, None, None, None, None),

    ("MWT-EBU-80G-020", "E-Band Backhaul Unit 80GHz",
     "E-Band Unit", "Millimeter Wave Backhaul", "Microwave and Transport",
     "Transport Product Manager", "OLD",
     "RFC-DUP-WB-030", 2, "PWR-PAB-35G-033", 1, None, None),

    ("MWT-DBU-150G-021", "D-Band Backhaul Unit 150GHz",
     "D-Band Unit", "Millimeter Wave Backhaul", "Microwave and Transport",
     "NPI Program Manager", "NPI",
     "RFC-DUP-WB-030", 2, "PWR-PAB-28G-034", 1, None, None),

    ("MWT-FGU-FH-022", "Fronthaul Gateway Unit",
     "Transport Node", "Transport Node", "Microwave and Transport",
     "Transport Product Manager", "OLD",
     "BBP-BPC-5G-016", 2, "PWR-PSU-48V-031", 1, None, None),

    ("MWT-MAN-MH-023", "Midhaul Aggregation Node",
     "Transport Node", "Transport Node", "Microwave and Transport",
     "Transport Product Manager", "OLD",
     None, None, None, None, None, None),

    # ── Platform 4: RF Components and Filters ──────────────────────────────
    ("RFC-DPX-B3-024", "Band 3 RF Diplexer Filter",
     "RF Filter", "RF Filter Module", "RF Components and Filters",
     "RF Component Manager", "OLD",
     None, None, None, None, None, None),

    ("RFC-FLT-B78-025", "Band 78 5G NR Filter Module",
     "RF Filter", "RF Filter Module", "RF Components and Filters",
     "RF Component Manager", "OLD",
     None, None, None, None, None, None),

    ("RFC-TFL-S6G-026", "Sub-6GHz Tunable Filter",
     "RF Filter", "RF Filter Module", "RF Components and Filters",
     "NPI Program Manager", "NPI",
     None, None, None, None, None, None),

    ("RFC-LNA-35G-027", "Low Noise Amplifier 3.5GHz",
     "RF Amplifier", "RF Amplifier", "RF Components and Filters",
     "RF Component Manager", "OLD",
     None, None, None, None, None, None),

    ("RFC-HPA-21G-028", "High Power Amplifier 2.1GHz",
     "RF Amplifier", "RF Amplifier", "RF Components and Filters",
     "RF Component Manager", "OLD",
     None, None, None, None, None, None),

    ("RFC-DUP-B1-029", "Antenna Duplexer Unit Band 1",
     "Duplexer", "Duplexer Unit", "RF Components and Filters",
     "RF Component Manager", "OLD",
     None, None, None, None, None, None),

    ("RFC-DUP-WB-030", "Wideband Duplexer 600-2700MHz",
     "Duplexer", "Duplexer Unit", "RF Components and Filters",
     "NPI Program Manager", "NPI",
     None, None, None, None, None, None),

    # ── Platform 5: Power and Infrastructure ───────────────────────────────
    ("PWR-PSU-48V-031", "48V DC Power Supply 1200W",
     "Power Supply Unit", "Power Supply Unit", "Power and Infrastructure",
     "Power Systems Manager", "OLD",
     "PWR-PSU-48V-032", 2, None, None, None, None),

    ("PWR-PSU-48V-032", "48V DC Power Supply Board 600W",
     "Power Supply Board", "Power Supply Unit", "Power and Infrastructure",
     "Power Systems Manager", "OLD",
     None, None, None, None, None, None),

    ("PWR-PAB-35G-033", "GaN Power Amplifier Board 3.5GHz",
     "Power Amplifier Board", "Power Amplifier Board", "Power and Infrastructure",
     "Power Systems Manager", "OLD",
     None, None, None, None, None, None),

    ("PWR-PAB-28G-034", "GaN Power Amplifier Board 28GHz",
     "Power Amplifier Board", "Power Amplifier Board", "Power and Infrastructure",
     "NPI Program Manager", "NPI",
     None, None, None, None, None, None),

    ("PWR-RET-ACT-035", "Remote Electrical Tilt Actuator Unit",
     "RET Unit", "Remote Electrical Tilt", "Power and Infrastructure",
     "Power Systems Manager", "OLD",
     None, None, None, None, None, None),
]


def generate_product_master() -> pd.DataFrame:
    rows = []
    for p in PRODUCTS:
        (pn, desc, ptype, family, platform, poc, status,
         c1_pn, c1_qty, c2_pn, c2_qty, c3_pn, c3_qty) = p

        has_children = c1_pn is not None
        is_parent = has_children

        rows.append({
            "prod_pk":             md5_key(pn),
            "product_number":      pn,
            "product_description": desc,
            "product_type":        ptype,
            "product_family":      family,
            "platform":            platform,
            "category":            platform.split("(")[0].strip()
                                   if "(" in platform else platform,
            "product_poc":         poc,
            "product_status":      status,
            "is_parent":           int(is_parent),
            "has_children":        int(has_children),
            "child_product_1":     c1_pn,
            "quantity_child_1":    c1_qty,
            "child_product_2":     c2_pn,
            "quantity_child_2":    c2_qty,
            "child_product_3":     c3_pn,
            "quantity_child_3":    c3_qty,
        })
    return pd.DataFrame(rows)


def generate_product_master_db(config: dict) -> pd.DataFrame:
    logger.info("=" * 60)
    logger.info("GENERATING: raw_product_master.db")
    logger.info("=" * 60)

    db_path = get_sqlite_path(
        config["databases"]["raw"]["product_master"], config
    )

    df = generate_product_master()
    write_to_sqlite(df, "product_master", db_path)

    parents = df[df["is_parent"] == 1]
    npi = df[df["product_status"] == "NPI"]
    logger.info(f"  Products: {len(df)} total | "
                f"{len(parents)} parents | {len(npi)} NPI")
    logger.success("raw_product_master.db complete")
    return df


if __name__ == "__main__":
    cfg = load_config()
    generate_product_master_db(cfg)