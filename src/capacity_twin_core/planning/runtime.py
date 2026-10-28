"""Shared release-pinned, read-only helpers for planning applications."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from capacity_twin_core.runtime.database_paths import get_release_pointer, get_runtime_home


class PlanningNotReadyError(RuntimeError):
    """The compatible self-contained Serving release is unavailable."""


def release_snapshot() -> dict[str, Any]:
    """Capture one compatible Serving publication for the whole request."""
    runtime = get_runtime_home().resolve()
    pointer = get_release_pointer(runtime)
    if not pointer.is_file():
        raise PlanningNotReadyError("No compatible release is promoted.")
    try:
        release = json.loads(pointer.read_text(encoding="utf-8"))
        serving = release["publications"]["serving"]
        candidate = Path(serving["path"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise PlanningNotReadyError("The compatible release pointer is invalid.") from error
    path = (candidate if candidate.is_absolute() else runtime / candidate).resolve()
    if runtime != path and runtime not in path.parents:
        raise PlanningNotReadyError("The promoted Serving path escapes the runtime home.")
    if not path.is_file():
        raise PlanningNotReadyError("The promoted Serving database is missing.")
    return {
        "release_id": release.get("release_id") or release.get("run_id"),
        "serving_run_id": serving.get("run_id"),
        "published_at": release.get("promoted_at") or release.get("created_at"),
        "path": path,
    }


@contextmanager
def serving_connection(
    required_tables: set[str] | frozenset[str],
) -> Iterator[tuple[duckdb.DuckDBPyConnection, dict[str, Any]]]:
    """Open only the pinned self-contained Serving database in read-only mode."""
    snapshot = release_snapshot()
    connection = duckdb.connect(str(snapshot["path"]), read_only=True)
    try:
        objects = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT table_name, table_type FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        missing = sorted(required_tables - objects.keys())
        views = sorted(name for name in required_tables if objects.get(name) != "BASE TABLE")
        if missing or views:
            details = []
            if missing:
                details.append(f"missing {', '.join(missing)}")
            if views:
                details.append(f"not materialized {', '.join(views)}")
            raise PlanningNotReadyError(
                "The Serving contract is not ready: " + "; ".join(details)
            )
        yield connection, snapshot
    except duckdb.Error as error:
        raise PlanningNotReadyError("The promoted Serving database could not be read.") from error
    finally:
        connection.close()


def rows(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Return JSON-safe rows for one bounded parameterized query."""
    relation = connection.execute(sql, params or [])
    columns = [item[0] for item in relation.description]
    return [
        {
            column: float(value) if isinstance(value, Decimal) else value
            for column, value in zip(columns, record)
        }
        for record in relation.fetchall()
    ]


def option(value: Any, label: Any | None = None) -> dict[str, str]:
    """Return a code plus a full display label."""
    code = str(value)
    text = str(label or code)
    return {"value": code, "code": code, "label": text if code in text else f"{text} ({code})"}


def release_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return browser-safe release provenance."""
    return {
        "release_id": snapshot["release_id"],
        "serving_run_id": snapshot["serving_run_id"],
        "published_at": snapshot["published_at"],
    }


def health_payload(
    app_name: str,
    required_tables: set[str] | frozenset[str],
) -> dict[str, Any]:
    """Report readiness and table counts without mutating runtime."""
    try:
        with serving_connection(required_tables) as (connection, snapshot):
            counts = {
                table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                for table in sorted(required_tables)
            }
    except PlanningNotReadyError as error:
        return {
            "status": "not-ready",
            "app": app_name,
            "reason": str(error),
            "release_id": None,
            "tables": {},
        }
    return {
        "status": "ready",
        "app": app_name,
        "release_id": snapshot["release_id"],
        "serving_run_id": snapshot["serving_run_id"],
        "published_at": snapshot["published_at"],
        "tables": counts,
    }
