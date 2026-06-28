"""
Gold layer utilities.
Capacity math formulas, bottleneck classification,
DuckDB write helpers.
"""

import hashlib
import pandas as pd
import duckdb
from src.utils.logger import logger


def md5_key(*args) -> str:
    raw = "|".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()


def classify_bottleneck(gap_pct: float) -> str:
    """
    Classify capacity gap severity using semiconductor industry thresholds.
    gap_pct = (capacity - demand) / demand
    Positive = surplus, Negative = shortage.
    """
    if gap_pct is None:
        return "UNKNOWN"
    if gap_pct > 0.15:
        return "EXCESS"
    elif gap_pct > 0.05:
        return "BALANCED"
    elif gap_pct >= 0:
        return "LOW"
    elif gap_pct >= -0.03:
        return "MEDIUM"
    elif gap_pct >= -0.08:
        return "HIGH"
    else:
        return "CRITICAL"


def write_gold_table(
    df: pd.DataFrame,
    table_name: str,
    duck_conn: duckdb.DuckDBPyConnection,
    indexes: list[str] = None,
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