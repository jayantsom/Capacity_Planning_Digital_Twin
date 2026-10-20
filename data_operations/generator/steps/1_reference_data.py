# ruff: noqa: N999
"""Step 1: write sites, tests, manufacturers, and resource contracts."""

from data_operations.generator.generators.reference_data import generate_reference_data


def run(config: dict):
    """Generate the reference database for later steps."""
    return generate_reference_data(config)
