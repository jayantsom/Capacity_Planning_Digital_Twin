# ruff: noqa: N999 - ordered workflow filenames are an app contract
"""Run the measured production-yield workflow."""

from decision_intelligence.ml.models.yield_prediction import run_yield_prediction


def run() -> dict:
    """Execute yield preparation, holdout evaluation, SHAP, and output staging."""
    return run_yield_prediction()
