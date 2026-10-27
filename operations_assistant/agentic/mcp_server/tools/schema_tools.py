"""
Schema discovery tools
Agents call these to understand what tables/views exist and their columns.
Critical for the router and for the run_query fallback tool.
"""

from operations_assistant.agentic.mcp_server.db import get_conn, query
from operations_assistant.agentic.mcp_server.sql_security import (
    SqlValidationError,
    clamp_limit,
    require_identifier,
)


def _allowed_schema() -> dict[str, set[str]]:
    """Load the current promoted schema as the identifier allowlist."""
    conn = get_conn()
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' "
                "AND (table_name LIKE 'gold_%' OR table_name LIKE 'srv_vw_%')"
            ).fetchall()
        ]
        return {
            table: {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'main' AND table_name = ?",
                    [table],
                ).fetchall()
            }
            for table in tables
        }
    finally:
        conn.close()


def list_tables() -> dict:
    """
    List all gold tables and serving views available in the DuckDB gold layer.

    Returns:
        {"tables": [...], "views": [...]}
    """
    sql_tables = """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND (table_name LIKE 'gold_%' OR table_name LIKE 'srv_vw_%')
        ORDER BY table_type, table_name
    """
    try:
        rows = query(sql_tables)
        tables = [r["table_name"] for r in rows if r["table_type"] == "BASE TABLE"]
        views  = [r["table_name"] for r in rows if r["table_type"] == "VIEW"]
        return {"tables": tables, "views": views,
                "total": len(tables) + len(views)}
    except Exception:
        return {"error": "Schema information is unavailable."}


def get_schema(table_name: str) -> dict:
    """
    Return column names and types for a given table or view.

    Args:
        table_name: Name of the table or view (e.g. 'gold_bottleneck').

    Returns:
        {"table": "...", "columns": [{"name": ..., "type": ...}, ...]}
    """
    try:
        schema = _allowed_schema()
        safe_table = require_identifier(table_name, schema, "table")
        rows = query(f"DESCRIBE {safe_table}")
        columns = [{"name": r["column_name"], "type": r["column_type"]}
                   for r in rows]
        return {"table": table_name, "columns": columns,
                "column_count": len(columns)}
    except SqlValidationError as error:
        return {"error": str(error)}
    except Exception:
        return {"error": "Schema information is unavailable."}


def get_table_preview(table_name: str, limit: int = 5) -> dict:
    """
    Return a small sample of rows from a table or view.
    Useful for agents to understand data shape before querying.

    Args:
        table_name: Name of the table or view.
        limit:      Number of rows to preview (max 20).

    Returns:
        {"columns": [...], "rows": [...]}
    """
    try:
        schema = _allowed_schema()
        safe_table = require_identifier(table_name, schema, "table")
        safe_limit = clamp_limit(limit, maximum=20)
        rows = query(f"SELECT * FROM {safe_table} LIMIT {safe_limit}")
        return {"table": table_name,
                "columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except SqlValidationError as error:
        return {"error": str(error)}
    except Exception:
        return {"error": "Table preview is unavailable."}


def get_distinct_values(table_name: str, column_name: str, limit: int = 50) -> dict:
    """
    Return distinct values for a column — useful for agents to know valid
    filter values (e.g. all site_codes, all test_types).

    Args:
        table_name:  Table or view to query.
        column_name: Column to get distinct values for.
        limit:       Max distinct values to return (max 200).

    Returns:
        {"column": ..., "values": [...], "count": N}
    """
    try:
        schema = _allowed_schema()
        safe_table = require_identifier(table_name, schema, "table")
        safe_column = require_identifier(
            column_name, schema.get(table_name, set()), "column"
        )
        safe_limit = clamp_limit(limit, maximum=200)
        rows = query(
            f"SELECT DISTINCT {safe_column} FROM {safe_table} "
            f"ORDER BY {safe_column} LIMIT {safe_limit}"
        )
        values = [next(iter(row.values())) for row in rows]
        return {"table": table_name, "column": column_name,
                "values": values, "count": len(values)}
    except SqlValidationError as error:
        return {"error": str(error)}
    except Exception:
        return {"error": "Distinct values are unavailable."}
