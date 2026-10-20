# ruff: noqa: N999 - ordered workflow filenames are an app contract
"""Run the leakage-safe demand forecasting workflow."""

from decision_intelligence.ml.models.demand_forecast import run_demand_forecast


def run() -> dict:
    """Execute demand preparation, temporal evaluation, fit, and output staging."""
    return run_demand_forecast()
