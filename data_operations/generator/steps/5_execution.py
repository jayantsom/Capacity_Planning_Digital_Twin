# ruff: noqa: N999
"""Step 5: write canonical MI execution events."""

from data_operations.generator.generators.mi_execution import generate_mi_execution_db


def run(config: dict):
    """Generate execution once so downstream facts can derive from it."""
    return generate_mi_execution_db(config)
