"""Read globally configured windows and resolve safe query predicates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import duckdb

from capacity_twin_core.runtime.database_paths import (
    get_control_run_pointer,
    get_runtime_home,
)

WindowGrain = Literal["date", "month_key"]

WINDOW_DISPLAY_NAMES = {
    "total": "Total",
    "band_1": "Snapshot 1",
    "band_2": "Snapshot 2",
}

TIME_COLUMN_GRAINS: tuple[tuple[str, WindowGrain], ...] = (
    ("execution_date", "date"),
    ("event_date", "date"),
    ("event_timestamp", "date"),
    ("period_start", "date"),
    ("month_key", "month_key"),
    ("forecast_month_key", "month_key"),
    ("month", "month_key"),
)


@dataclass(frozen=True)
class ComparisonWindow:
    """One immutable globally configured analytical date window."""

    window_id: str
    display_name: str
    start_date: date | None
    end_date: date | None
    sort_order: int

    def as_dict(self) -> dict:
        value = asdict(self)
        value["start_date"] = self.start_date.isoformat() if self.start_date else None
        value["end_date"] = self.end_date.isoformat() if self.end_date else None
        return value


def _control_database(runtime_home: Path | None = None) -> Path:
    pointer = get_control_run_pointer(runtime_home or get_runtime_home())
    if not pointer.is_file():
        raise FileNotFoundError("Control catalog has not been generated")
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    database = Path(payload["database"]).resolve()
    if not database.is_file():
        raise FileNotFoundError(f"Control catalog database is missing: {database}")
    return database


def list_comparison_windows(runtime_home: Path | None = None) -> list[ComparisonWindow]:
    """Return Total, Snapshot 1, and Snapshot 2 in display order."""
    database = _control_database(runtime_home)
    with duckdb.connect(str(database), read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT window_id, display_name, start_date, end_date, sort_order
            FROM comparison.comparison_window
            ORDER BY sort_order
            """
        ).fetchall()
    windows = [
        ComparisonWindow(
            window_id=row[0],
            display_name=WINDOW_DISPLAY_NAMES.get(row[0], row[1]),
            start_date=date.fromisoformat(str(row[2])) if row[2] else None,
            end_date=date.fromisoformat(str(row[3])) if row[3] else None,
            sort_order=int(row[4]),
        )
        for row in rows
    ]
    expected = {"total", "band_1", "band_2"}
    if {window.window_id for window in windows} != expected:
        raise ValueError("Control catalog must define Total, Snapshot 1, and Snapshot 2")
    return windows


def get_comparison_window(
    window_id: str,
    runtime_home: Path | None = None,
) -> ComparisonWindow:
    """Resolve one stable ID or reject it explicitly."""
    normalized = window_id.strip().lower()
    if normalized == "total":
        return ComparisonWindow(
            "total", WINDOW_DISPLAY_NAMES["total"], None, None, 0
        )
    for window in list_comparison_windows(runtime_home):
        if window.window_id == normalized:
            return window
    raise ValueError(f"Unknown comparison window: {window_id}")


def resolve_time_column(column_names: set[str]) -> tuple[str, WindowGrain] | None:
    """Choose one canonical date column and its safe comparison grain."""
    return next(
        (
            (column_name, grain)
            for column_name, grain in TIME_COLUMN_GRAINS
            if column_name in column_names
        ),
        None,
    )


def window_predicate(
    window: ComparisonWindow,
    column: str,
    grain: WindowGrain,
) -> tuple[str, list[str | int]]:
    """Return a parameterized inclusive predicate for a declared time column."""
    if window.window_id == "total":
        return "", []
    if window.start_date is None or window.end_date is None:
        raise ValueError(f"Window {window.window_id} does not define date bounds")
    if grain == "date":
        return f'"{column}" BETWEEN ? AND ?', [
            window.start_date.isoformat(),
            window.end_date.isoformat(),
        ]
    if grain == "month_key":
        start = window.start_date.year * 100 + window.start_date.month
        end = window.end_date.year * 100 + window.end_date.month
        return f'"{column}" BETWEEN ? AND ?', [start, end]
    raise ValueError(f"Unsupported comparison-window grain: {grain}")
