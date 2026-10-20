# ruff: noqa: N999 - ordered workflow filenames are an app contract
"""Run the deterministic CapEx Monte Carlo simulation."""

from decision_intelligence.ml.models.capex_montecarlo import run_capex_montecarlo


def run() -> dict:
    """Execute uncertainty estimation, simulation, and output staging."""
    return run_capex_montecarlo()
