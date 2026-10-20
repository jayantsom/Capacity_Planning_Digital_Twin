"""Helpers for isolated layer databases and safe cross-layer reads."""

from __future__ import annotations

from pathlib import Path

import duckdb


def open_staging_database(path: Path) -> duckdb.DuckDBPyConnection:
    """Create a fresh candidate database that is not visible to readers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    return duckdb.connect(str(path))


def attach_read_only(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    alias: str,
) -> None:
    """Attach one immutable upstream database to a downstream candidate."""
    escaped = str(path.resolve()).replace("'", "''")
    connection.execute(f"ATTACH '{escaped}' AS {alias} (READ_ONLY)")


def expose_tables(
    connection: duckdb.DuckDBPyConnection,
    source_alias: str,
    prefix: str,
) -> list[str]:
    """Expose matching upstream tables as temporary compatibility views."""
    rows = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_catalog = ? AND table_name LIKE ?
        ORDER BY table_name
        """,
        [source_alias, f"{prefix}%"],
    ).fetchall()
    names = [row[0] for row in rows]
    for name in names:
        connection.execute(
            f'CREATE OR REPLACE TEMP VIEW "{name}" AS '
            f'SELECT * FROM {source_alias}."{name}"'
        )
    return names


def assert_unique_grain(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    columns: list[str],
) -> None:
    """Fail before publication when a declared business grain is multiplied."""
    quoted = ", ".join(f'"{column}"' for column in columns)
    duplicate = connection.execute(
        f"""
        SELECT {quoted}, COUNT(*) AS row_count
        FROM "{table_name}"
        GROUP BY {quoted}
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).fetchone()
    if duplicate:
        raise ValueError(
            f"{table_name} violates unique grain {columns}; example={duplicate}"
        )


def table_names(
    connection: duckdb.DuckDBPyConnection,
    *,
    prefix: str,
) -> list[str]:
    """List local tables with a stable order."""
    return [
        row[0]
        for row in connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_catalog = current_database()
              AND table_type = 'BASE TABLE'
              AND table_name LIKE ?
            ORDER BY table_name
            """,
            [f"{prefix}%"],
        ).fetchall()
    ]
