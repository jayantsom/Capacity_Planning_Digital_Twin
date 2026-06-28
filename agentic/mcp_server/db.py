"""
Shared DuckDB connection for MCP server tools.
Read-only connection — tools never write to the gold layer.
"""

from pathlib import Path
import duckdb

# Resolve DB path relative to project root (2 levels up from agentic/mcp_server/)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DB_PATH = _PROJECT_ROOT / "data" / "capacity_planning_twin.duckdb"


def get_conn() -> duckdb.DuckDBPyConnection:
    """Return a read-only DuckDB connection to the analytics database."""
    if not _DB_PATH.exists():
        raise FileNotFoundError(f"DuckDB not found at {_DB_PATH}")
    return duckdb.connect(str(_DB_PATH), read_only=True)


def query(sql: str, params: list | None = None) -> list[dict]:
    """
    Execute a SQL query and return results as a list of dicts.
    Each dict maps column_name → value.
    """
    conn = get_conn()
    try:
        rel = conn.execute(sql, params or [])
        cols = [d[0] for d in rel.description]
        rows = rel.fetchall()
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()


def query_df(sql: str, params: list | None = None):
    """Execute SQL and return a pandas DataFrame."""
    conn = get_conn()
    try:
        return conn.execute(sql, params or []).df()
    finally:
        conn.close()
