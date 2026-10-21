# ruff: noqa: N999
"""Step 6: derive test parameters from Machine execution."""

from data_operations.generator.generators.machine_test_param import generate_machine_test_param_db


def run(config: dict):
    """Create parameter rows that reconcile to execution quantities."""
    return generate_machine_test_param_db(config)
