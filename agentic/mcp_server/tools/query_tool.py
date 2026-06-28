"""
Fallback tool: run_query
Allows agents to execute any read-only SQL against the DuckDB gold layer.
Used when no pre-defined tool matches the user's question.
Safety: read-only connection + SQL guard rejects any mutating statements.
"""

from agentic.mcp_server.db import query


_BLOCKED = ("insert", "update", "delete", "drop", "create", "alter",
            "truncate", "replace", "merge", "copy", "attach", "detach")


def _is_safe(sql: str) -> bool:
    first = sql.strip().split()[0].lower()
    return first not in _BLOCKED


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
    if not _is_safe(sql):
        return {"error": "Only SELECT queries are permitted."}

    limit = min(int(limit), 2000)

    # Wrap in a limit if not already present
    normalised = sql.rstrip().rstrip(";")
    if "limit" not in normalised.lower():
        normalised = f"{normalised} LIMIT {limit}"

    try:
        rows = query(normalised)
        columns = list(rows[0].keys()) if rows else []
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
    except Exception as e:
        return {"error": str(e)}
