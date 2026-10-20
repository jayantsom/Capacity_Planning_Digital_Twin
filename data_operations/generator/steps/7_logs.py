# ruff: noqa: N999
"""Step 7: derive bounded logs from MI execution excursions."""

from data_operations.generator.generators.mi_logs import generate_mi_logs_db


def run(config: dict):
    """Create logs that always reference a real execution record."""
    return generate_mi_logs_db(config)
