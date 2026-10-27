"""Shared comparison-window contracts for analytical applications."""

from capacity_twin_core.comparison.windows import (
    ComparisonWindow,
    get_comparison_window,
    list_comparison_windows,
    resolve_time_column,
    window_predicate,
)

__all__ = [
    "ComparisonWindow",
    "get_comparison_window",
    "list_comparison_windows",
    "resolve_time_column",
    "window_predicate",
]
