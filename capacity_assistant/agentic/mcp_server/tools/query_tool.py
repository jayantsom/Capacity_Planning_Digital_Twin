"""Bounded custom-query tool for the promoted read-only analytics schema."""

from capacity_assistant.agentic.mcp_server.db import query_custom
from capacity_assistant.agentic.mcp_server.sql_security import SqlValidationError, clamp_limit


def run_query(sql: str, limit: int = 500) -> dict:
    """
    Execute any read-only SQL query against the gold layer.

    Args:
        sql:   A SELECT (or WITH ... SELECT) statement.
        limit: Max rows to return (default 500, capped at 2000).

    Returns:
        {"columns": [...], "rows": [...], "row_count": N}
        or {"error": "..."} on failure.
    """
    try:
        safe_limit = clamp_limit(limit)
        rows = query_custom(sql, safe_limit)
        columns = list(rows[0].keys()) if rows else []
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
    except SqlValidationError as error:
        return {"error": str(error)}
    except Exception:
        return {"error": "The query could not be completed."}
