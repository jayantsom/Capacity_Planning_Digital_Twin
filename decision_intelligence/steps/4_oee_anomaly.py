# ruff: noqa: N999 - ordered workflow filenames are an app contract
"""Run the historical-fit OEE anomaly workflow."""

from decision_intelligence.ml.models.oee_anomaly import run_oee_anomaly


def run() -> dict:
    """Execute anomaly preparation, historical fit, scoring, and output staging."""
    return run_oee_anomaly()
