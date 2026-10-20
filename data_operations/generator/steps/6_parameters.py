# ruff: noqa: N999
"""Step 6: derive test parameters from MI execution."""

from data_operations.generator.generators.mi_test_param import generate_mi_test_param_db


def run(config: dict):
    """Create parameter rows that reconcile to execution quantities."""
    return generate_mi_test_param_db(config)
