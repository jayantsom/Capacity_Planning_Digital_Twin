"""
Site-Product Assignment Matrix.
Defines which products are manufactured at which sites.
This is the master join table used by all planning generators.
No SQLite output — used as an in-memory dependency.
"""

from src.generators.product_master import PRODUCTS
from src.generators.reference_data import SITES

# ── Supplier → Platform mapping ────────────────────────────────────────────────
# Defines which platforms each supplier manufactures.
# Mirrors Topic 6 generation rules exactly.

SUPPLIER_PLATFORM_MAP = {
    "Ericsson": [
        "Radio Access (RAN)",
        "Microwave and Transport",
        "Baseband and Processing",
    ],
    "Jabil": [
        "Radio Access (RAN)",
        "Baseband and Processing",
        "RF Components and Filters",
    ],
    "Flex": [
        "RF Components and Filters",
        "Power and Infrastructure",
    ],
    "Infineon": [
        "RF Components and Filters",
        "Power and Infrastructure",
    ],
    "Sanmina": [
        "Baseband and Processing",
        "Power and Infrastructure",
    ],
    "Luxshare": [
        "RF Components and Filters",
        "Radio Access (RAN)",
    ],
}

# ── Test type → Product family mapping ────────────────────────────────────────
# Which test types apply to which product families.
# Drives target_test_time and target_yield generation.

FAMILY_TEST_TYPE_MAP = {
    "Massive MIMO Radio":      ["OTA", "TRX", "PAM", "UC", "ALT", "AT"],
    "Sub-6GHz Radio":          ["OTA", "TRX", "UC", "AT"],
    "mmWave Radio":            ["OTA", "TRX", "PAM", "UC", "AT"],
    "Active Antenna Unit":     ["OTA", "TRX", "PIM", "UC", "AT"],
    "Baseband Unit":           ["FCT", "TRX", "BIT", "ALT", "AT"],
    "Digital Unit":            ["FCT", "TRX", "BIT", "AT"],
    "Baseband Card":           ["FCT", "ICT", "AT"],
    "Microwave Link":          ["TRX", "UC", "ALT", "AT"],
    "Millimeter Wave Backhaul":["TRX", "PAM", "UC", "AT"],
    "Transport Node":          ["FCT", "BIT", "AT"],
    "RF Filter Module":        ["PIM", "ICT", "AT"],
    "RF Amplifier":            ["PAM", "ICT", "AT"],
    "Duplexer Unit":           ["PIM", "ICT", "AT"],
    "Power Supply Unit":       ["FCT", "ICT", "BIT", "AT"],
    "Power Supply Board":      ["FCT", "ICT", "AT"],
    "Power Amplifier Board":   ["PAM", "ICT", "AT"],
    "Remote Electrical Tilt":  ["FCT", "AT"],
}

# ── NPI site restriction ───────────────────────────────────────────────────────
# NPI products only manufactured at 2-3 qualified sites.
NPI_QUALIFIED_SITES = {
    "RAN-AAU-35128-004": ["ERI_STK", "JAB_SGP"],
    "RAN-MWR-3900-009":  ["ERI_STK", "INF_TSE"],
    "BBP-BBU-6GPR-013":  ["ERI_STK", "SAN_AUS"],
    "BBP-DPU-G4-015":    ["ERI_STK", "SAN_AUS", "JAB_SGP"],
    "MWT-DBU-150G-021":  ["ERI_STK", "INF_MUN"],
    "RFC-TFL-S6G-026":   ["INF_MUN", "INF_SEO"],
    "RFC-DUP-WB-030":    ["INF_MUN", "FLX_SZN"],
    "PWR-PAB-28G-034":   ["INF_MUN", "INF_TSE", "SAN_AUS"],
}


def build_assignment_matrix() -> list[dict]:
    """
    Build the full site-product assignment matrix.
    Returns list of dicts: {site_code, supplier, product_number,
                            product_family, platform, product_status,
                            test_types}
    """
    # Build lookup maps
    site_supplier = {s[0]: s[3] for s in SITES}

    product_map = {}
    for p in PRODUCTS:
        pn = p[0]
        product_map[pn] = {
            "product_number":  pn,
            "product_family":  p[3],
            "platform":        p[4],
            "product_status":  p[6],
        }

    assignments = []

    for site_code, _, _, supplier, *_ in SITES:
        allowed_platforms = SUPPLIER_PLATFORM_MAP.get(supplier, [])

        for pn, prod in product_map.items():
            platform = prod["platform"]
            status   = prod["product_status"]
            family   = prod["product_family"]

            # Platform filter
            if platform not in allowed_platforms:
                continue

            # NPI site restriction
            if status == "NPI":
                qualified = NPI_QUALIFIED_SITES.get(pn, [])
                if site_code not in qualified:
                    continue

            # Test types for this product family
            test_types = FAMILY_TEST_TYPE_MAP.get(family, ["AT"])

            assignments.append({
                "site_code":      site_code,
                "supplier":       supplier,
                "product_number": pn,
                "product_family": family,
                "platform":       platform,
                "product_status": status,
                "test_types":     test_types,
            })

    return assignments


# Singleton — built once, imported everywhere
ASSIGNMENT_MATRIX = build_assignment_matrix()

# Quick lookup sets
SITE_PRODUCT_PAIRS = {
    (a["site_code"], a["product_number"])
    for a in ASSIGNMENT_MATRIX
}

SITE_PRODUCT_TEST_TRIPLES = {
    (a["site_code"], a["product_number"], tt)
    for a in ASSIGNMENT_MATRIX
    for tt in a["test_types"]
}


def get_products_for_site(site_code: str) -> list[dict]:
    return [a for a in ASSIGNMENT_MATRIX if a["site_code"] == site_code]


def get_sites_for_product(product_number: str) -> list[str]:
    return [a["site_code"] for a in ASSIGNMENT_MATRIX
            if a["product_number"] == product_number]


def get_test_types_for_family(family: str) -> list[str]:
    return FAMILY_TEST_TYPE_MAP.get(family, ["AT"])


if __name__ == "__main__":
    from src.utils.logger import logger
    matrix = ASSIGNMENT_MATRIX
    logger.info(f"Assignment matrix: {len(matrix)} site-product pairs")
    sites_covered = len({a['site_code'] for a in matrix})
    products_covered = len({a['product_number'] for a in matrix})
    logger.info(f"  Sites covered:    {sites_covered}/22")
    logger.info(f"  Products covered: {products_covered}/35")

    triples = SITE_PRODUCT_TEST_TRIPLES
    logger.info(f"  Site-product-test triples: {len(triples)}")