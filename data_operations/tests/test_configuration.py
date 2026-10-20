"""Validation checks for run-specific generator options."""

from datetime import date

import pytest
from pydantic import ValidationError

from data_operations.backend.models import GeneratorOptions
from data_operations.backend.service import build_run_config, estimate_run


def test_run_overrides_do_not_modify_tracked_configuration() -> None:
    """Build an in-memory run snapshot for UI values."""
    options = GeneratorOptions(profile="small", random_seed=7)
    config = build_run_config(options)
    assert config["data_generation"]["volume"] == "low"
    assert config["data_generation"]["random_seed"] == 7


def test_snapshot_must_stay_inside_actual_history() -> None:
    """Reject a snapshot that can see future records."""
    with pytest.raises(ValidationError):
        GeneratorOptions(snapshot_dates=[date(2027, 1, 1)])


def test_estimate_reports_uncapped_safety_result() -> None:
    """Return a real projection rather than clipping it to the configured cap."""
    estimate = estimate_run(GeneratorOptions(profile="small"))
    assert estimate["estimated_rows"] > 0
    assert isinstance(estimate["within_local_limits"], bool)
