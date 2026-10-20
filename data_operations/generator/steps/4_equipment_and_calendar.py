# ruff: noqa: N999
"""Step 4: write sparse equipment inventory and site calendars."""

from data_operations.generator.generators.site_equipment_inventory import (
    generate_site_equipment_inventory_db,
)
from data_operations.generator.generators.site_soft import generate_site_soft_db


def run(config: dict):
    """Generate resource inventory and operating-calendar inputs."""
    return generate_site_equipment_inventory_db(config), generate_site_soft_db(config)
