"""Short-lived, read-only DuckDB access for Capacity Assistant MCP tools."""

import json
import threading
from pathlib import Path

import duckdb

from capacity_assistant.agentic.mcp_server.sql_security import validate_read_only_query
from capacity_twin_core.runtime.database_paths import (
    get_active_run_pointer,
    get_runtime_home,
    load_app_config,
)


class DatabaseUnavailableError(RuntimeError):
    """Raised when the promoted analytics database cannot be read."""


class QueryTimeoutError(RuntimeError):
    """Raised when a database query exceeds its configured deadline."""


def _active_artifact_path(runtime_home: Path) -> Path | None:
    """Resolve an optional atomically promoted run without exposing its details."""
    pointer = get_active_run_pointer(runtime_home)
    if not pointer.is_file():
        return None
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    serving_database = payload.get("serving_database")
    if serving_database:
        serving_path = Path(serving_database)
        if not serving_path.is_absolute():
            serving_path = runtime_home / serving_path
        return serving_path.parent
    candidate = payload.get("artifact_path") or payload.get("path")
    if candidate:
        path = Path(candidate)
        return path if path.is_absolute() else runtime_home / path
    run_id = (
        payload.get("active_run_id")
        or payload.get("run_id")
        or payload.get("current_run_id")
    )
    return runtime_home / "artifacts" / str(run_id) if run_id else None


def database_path() -> Path:
    """Resolve the currently promoted read-only analytics database."""
    pipeline_config = load_app_config("data_operations.pipeline")
    database_names = pipeline_config["databases"]
    runtime_home = get_runtime_home()
    artifact = _active_artifact_path(runtime_home)
    if artifact:
        candidate = artifact / database_names["serving"]
        if candidate.is_file():
            return candidate
    return runtime_home / database_names["serving"]


def get_conn() -> duckdb.DuckDBPyConnection:
    """Return a read-only DuckDB connection to the analytics database."""
    path = database_path()
    if not path.is_file():
        raise DatabaseUnavailableError("The analytics database is unavailable.")
    try:
        return duckdb.connect(str(path), read_only=True)
    except duckdb.Error as error:
        raise DatabaseUnavailableError("The analytics database is unavailable.") from error


def _query_timeout_seconds() -> float:
    cfg = load_app_config("capacity_assistant").get("agentic", {})
    return max(0.1, float(cfg.get("database_timeout_seconds", 15)))


def _execute(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list | None,
) -> list[dict]:
    """Execute with a timer that interrupts DuckDB at the local deadline."""
    timed_out = threading.Event()

    def interrupt() -> None:
        timed_out.set()
        conn.interrupt()

    timer = threading.Timer(_query_timeout_seconds(), interrupt)
    timer.daemon = True
    timer.start()
    try:
        rel = conn.execute(sql, params or [])
        cols = [description[0] for description in rel.description]
        rows = rel.fetchall()
        return [dict(zip(cols, row)) for row in rows]
    except duckdb.Error as error:
        if timed_out.is_set():
            raise QueryTimeoutError("The database query timed out.") from error
        raise
    finally:
        timer.cancel()


def query(sql: str, params: list | None = None) -> list[dict]:
    """
    Execute a SQL query and return results as a list of dicts.
    Each dict maps column_name → value.
    """
    conn = get_conn()
    try:
        return _execute(conn, sql, params)
    finally:
        conn.close()


def query_custom(sql: str, limit: int) -> list[dict]:
    """Validate and execute one bounded custom query."""
    conn = get_conn()
    try:
        allowed_tables = [
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' "
                "AND (table_name LIKE 'gold_%' OR table_name LIKE 'srv_vw_%')"
            ).fetchall()
        ]
        validated = validate_read_only_query(sql, conn, allowed_tables, limit=limit)
        return _execute(conn, validated.sql, None)
    finally:
        conn.close()


def query_df(sql: str, params: list | None = None):
    """Execute SQL and return a pandas DataFrame."""
    conn = get_conn()
    try:
        rows = _execute(conn, sql, params)
        import pandas as pd

        return pd.DataFrame(rows)
    finally:
        conn.close()
