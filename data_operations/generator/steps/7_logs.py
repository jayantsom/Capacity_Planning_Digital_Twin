# ruff: noqa: N999
"""Step 7: derive bounded logs from Machine execution excursions."""

from data_operations.generator.generators.machine_logs import generate_machine_logs_db


def run(config: dict):
    """Create logs that always reference a real execution record."""
    return generate_machine_logs_db(config)
