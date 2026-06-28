"""
Schema discovery tools
Agents call these to understand what tables/views exist and their columns.
Critical for the router and for the run_query fallback tool.
"""

from agentic.mcp_server.db import query


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
    except Exception as e:
        return {"error": str(e)}


def get_schema(table_name: str) -> dict:
    """
    Return column names and types for a given table or view.

    Args:
        table_name: Name of the table or view (e.g. 'gold_bottleneck').

    Returns:
        {"table": "...", "columns": [{"name": ..., "type": ...}, ...]}
    """
    sql = "DESCRIBE ?"
    try:
        rows = query(f"DESCRIBE {table_name}")
        columns = [{"name": r["column_name"], "type": r["column_type"]}
                   for r in rows]
        return {"table": table_name, "columns": columns,
                "column_count": len(columns)}
    except Exception as e:
        return {"error": str(e)}


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
    safe_limit = min(int(limit), 20)
    try:
        rows = query(f"SELECT * FROM {table_name} LIMIT {safe_limit}")
        return {"table": table_name,
                "columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}


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
    safe_limit = min(int(limit), 200)
    try:
        rows = query(
            f"SELECT DISTINCT {column_name} FROM {table_name} "
            f"ORDER BY {column_name} LIMIT {safe_limit}"
        )
        values = [list(r.values())[0] for r in rows]
        return {"table": table_name, "column": column_name,
                "values": values, "count": len(values)}
    except Exception as e:
        return {"error": str(e)}
