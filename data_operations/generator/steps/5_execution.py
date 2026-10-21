# ruff: noqa: N999
"""Step 5: write canonical Machine execution events."""

from data_operations.generator.generators.machine_execution import generate_machine_execution_db


def run(config: dict):
    """Generate execution once so downstream facts can derive from it."""
    return generate_machine_execution_db(config)
