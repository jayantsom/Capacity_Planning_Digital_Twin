"""
Gold layer utilities.
Capacity math formulas, bottleneck classification,
DuckDB write helpers.
"""

import hashlib

import duckdb
import pandas as pd

from capacity_twin_core.logging import logger


def md5_key(*args) -> str:
    raw = "|".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()


def write_gold_table(
    df: pd.DataFrame,
    table_name: str,
    duck_conn: duckdb.DuckDBPyConnection,
    indexes: list[str] | None = None,
) -> int:
    """Write Pandas DataFrame to DuckDB Gold table."""
    duck_conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    duck_conn.register("_temp_gold", df)
    duck_conn.execute(f"""
        CREATE TABLE {table_name} AS
        SELECT * FROM _temp_gold
    """)
    duck_conn.unregister("_temp_gold")

    if indexes:
        for col in indexes:
            if col in df.columns:
                duck_conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS
                    idx_{table_name}_{col}
                    ON {table_name} ({col})
                """)

    count = duck_conn.execute(
        f"SELECT COUNT(*) FROM {table_name}"
    ).fetchone()[0]
    logger.info(f"    {table_name}: {count:,} rows")
    return count