# ruff: noqa: N999
"""Step 3: write demand, target yield, and target test time."""

from data_operations.generator.generators.demand_forecast import generate_demand_forecast_db
from data_operations.generator.generators.target_test_time import generate_target_test_time_db
from data_operations.generator.generators.target_yield import generate_target_yield_db


def run(config: dict):
    """Generate the three planning datasets in dependency order."""
    return (
        generate_demand_forecast_db(config),
        generate_target_test_time_db(config),
        generate_target_yield_db(config),
    )
