# ruff: noqa: N999
"""Step 2: write products, BOMs, routes, and sparse sourcing."""

from data_operations.generator.generators.product_master import generate_product_master_db


def run(config: dict):
    """Generate product and manufacturing-level contracts."""
    return generate_product_master_db(config)
