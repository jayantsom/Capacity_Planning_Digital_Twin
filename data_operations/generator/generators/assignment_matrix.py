"""
Site-Product Assignment Matrix.
Defines which products are manufactured at which sites.
This is the master join table used by all planning generators.
No SQLite output — used as an in-memory dependency.
"""

from data_operations.generator.generators.product_master import PRODUCTS
from data_operations.generator.generators.reference_data import SITES

# ── Supplier → Platform mapping ────────────────────────────────────────────────
# Defines which platforms each supplier manufactures.
# Mirrors Topic 6 generation rules exactly.

SUPPLIER_PLATFORM_MAP = {
    "Erivon": [
        "Radio Access (RAN)",
        "Microwave and Transport",
        "Baseband and Processing",
        "IP and Optical Networking",
        "Fixed Access",
        "Enterprise Wireless",
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
    "Celestica": [
        "Baseband and Processing", "IP and Optical Networking", "Fixed Access",
    ],
    "Benchmark": [
        "Radio Access (RAN)", "IP and Optical Networking", "Enterprise Wireless",
    ],
    "Jemstech": ["Radio Access (RAN)", "Enterprise Wireless"],
    "GPC": ["IP and Optical Networking", "Fixed Access"],
    "Nautech": ["IP and Optical Networking", "Enterprise Wireless"],
}

# ── Test type → Product family mapping ────────────────────────────────────────
# Which test types apply to which product families.
# Drives target_test_time and target_yield generation.

FAMILY_TEST_TYPE_MAP = {
    "Massive MIMO Radio":      ["CRF", "MIMO", "OTA", "TRX", "ENV", "AT"],
    "Sub-6GHz Radio":          ["CRF", "OTA", "TRX", "UC", "AT"],
    "mmWave Radio":            ["CRF", "MWP", "OTA", "UC", "AT"],
    "Active Antenna Unit":     ["CRF", "MIMO", "OTA", "PIM", "AT"],
    "Baseband Unit":           ["FWP", "FCT", "TRX", "BIT", "AT"],
    "Digital Unit":            ["JTAG", "FWP", "FCT", "TIM", "AT"],
    "Baseband Card":           ["SPI", "AOI", "JTAG", "ICT", "FCT"],
    "Microwave Link":          ["MWP", "TRX", "UC", "ENV", "AT"],
    "Millimeter Wave Backhaul":["MWP", "TRX", "PAM", "UC", "AT"],
    "Transport Node":          ["FWP", "FCT", "ETH", "TIM", "AT"],
    "RF Filter Module":        ["AOI", "PIM", "ICT", "AT"],
    "RF Amplifier":            ["AXI", "PAM", "ICT", "AT"],
    "Duplexer Unit":           ["PIM", "ICT", "AT"],
    "Power Supply Unit":       ["AOI", "FCT", "PWR", "BIT", "AT"],
    "Power Supply Board":      ["SPI", "AOI", "ICT", "PWR"],
    "Power Amplifier Board":   ["AXI", "PAM", "ICT", "PWR"],
    "Remote Electrical Tilt":  ["FWP", "FCT", "AT"],
    "Router":                  ["FWP", "SER", "ETH", "TIM", "ENV", "AT"],
    "Enterprise Switch":       ["JTAG", "FWP", "SER", "ETH", "PWR", "AT"],
    "Optical Transport":       ["FWP", "SER", "OPT", "TIM", "ENV", "AT"],
    "Optical Access":          ["FWP", "OPT", "ETH", "PWR", "AT"],
    "Wireless Access":         ["FWP", "CRF", "ETH", "PWR", "ENV", "AT"],
    "Optical Line Card":       ["SPI", "AOI", "JTAG", "SER", "OPT"],
    "Optical Pluggable":       ["AXI", "SER", "OPT", "ENV"],
}

def build_assignment_matrix() -> list[dict]:
    """
    Build the full site-product assignment matrix.
    Returns list of dicts: {site_code, supplier, product_number,
                            product_family, platform, test_types}
    """
    product_map = {}
    for p in PRODUCTS:
        pn = p[0]
        product_map[pn] = {
            "product_number":  pn,
            "product_family":  p[3],
            "platform":        p[4],
        }

    assignments = []
    child_products = {
        child
        for product in PRODUCTS
        for child in (product[6], product[8], product[10])
        if child is not None
    }
    site_rows = list(SITES)

    for pn, prod in sorted(product_map.items()):
        platform = prod["platform"]
        family = prod["product_family"]
        candidates = [
            site[0]
            for site in site_rows
            if platform in SUPPLIER_PLATFORM_MAP.get(site[3], [])
        ]
        if not candidates:
            candidates = [site[0] for site in site_rows if site[3] == "Erivon"]
        # Products share qualified platform sites so the local profile does
        # not create a duplicate tester and fixture pool at every factory.
        selected_codes = candidates[:2]

        for site_code in dict.fromkeys(selected_codes):
            site = next(item for item in site_rows if item[0] == site_code)
            supplier = site[3]
            assignments.append({
                "site_code": site_code,
                "supplier": supplier,
                "supplier_role": (
                    "COMPONENT_SUPPLIER" if supplier == "Infineon" else "EMS_OR_SYNTHETIC_OWNER"
                ),
                "product_number": pn,
                "product_family": family,
                "platform": platform,
                "product_level": "CHILD" if pn in child_products else "PARENT",
                "test_types": FAMILY_TEST_TYPE_MAP.get(family, ["AT"]),
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
    from capacity_twin_core.logging import logger
    matrix = ASSIGNMENT_MATRIX
    logger.info(f"Assignment matrix: {len(matrix)} site-product pairs")
    sites_covered = len({a['site_code'] for a in matrix})
    products_covered = len({a['product_number'] for a in matrix})
    logger.info(f"  Sites covered:    {sites_covered}/22")
    logger.info(f"  Products covered: {products_covered}/35")

    triples = SITE_PRODUCT_TEST_TRIPLES
    logger.info(f"  Site-product-test triples: {len(triples)}")