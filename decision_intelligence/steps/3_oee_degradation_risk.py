# ruff: noqa: N999 - ordered workflow filenames are an app contract
"""Run the equipment-grain OEE degradation-risk workflow."""

from decision_intelligence.ml.models.predictive_maintenance import run_predictive_maintenance


def run() -> dict:
    """Execute degradation labeling, temporal evaluation, and output staging."""
    return run_predictive_maintenance()
