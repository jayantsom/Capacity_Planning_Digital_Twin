"""
Shared utilities for Silver transformations.
MD5 surrogate key generation, month explosion, forward fill.
"""

import hashlib
import re
from pyspark.sql import DataFrame, Window
import pyspark.sql.functions as F
from pyspark.sql.types import IntegerType, StringType
from src.utils.logger import logger


def md5_surrogate_key(df: DataFrame, key_cols: list[str],
                      output_col: str = "surrogate_pk") -> DataFrame:
    """
    Generate deterministic MD5 surrogate key from concatenated columns.
    Nulls in key columns are replaced with 'NULL' before hashing.
    """
    concat_expr = F.concat_ws(
        "|",
        *[F.coalesce(F.col(c).cast(StringType()), F.lit("NULL"))
          for c in key_cols]
    )
    return df.withColumn(output_col, F.md5(concat_expr))


def detect_month_columns(columns: list[str]) -> list[str]:
    """
    Detect horizontal month columns matching pattern: mon_YYYY
    e.g. jan_2023, dec_2027
    """
    pattern = re.compile(r"^[a-z]{3}_\d{4}$")
    return [c for c in columns if pattern.match(c)]


def month_label_to_key(label: str) -> int:
    """
    Convert month label to integer key.
    jan_2023 → 202301
    """
    month_map = {
        "jan": 1,  "feb": 2,  "mar": 3,  "apr": 4,
        "may": 5,  "jun": 6,  "jul": 7,  "aug": 8,
        "sep": 9,  "oct": 10, "nov": 11, "dec": 12,
    }
    parts = label.split("_")
    month_num = month_map.get(parts[0], 1)
    year = int(parts[1])
    return year * 100 + month_num


def explode_month_columns(
    df: DataFrame,
    value_col_name: str,
    cast_type: str = "double",
) -> DataFrame:
    """
    Unpivot horizontal month columns into rows.
    Casts all month columns to double before stacking
    to avoid Spark DATATYPE_MISMATCH error from mixed
    BIGINT/DOUBLE inference on SQLite numeric columns.

    Input:  site | product | jan_2023 | feb_2023 | ...
    Output: site | product | month_key | {value_col_name}
    """
    month_cols = detect_month_columns(df.columns)
    non_month_cols = [c for c in df.columns if c not in month_cols]

    if not month_cols:
        logger.warning("No month columns detected for explosion")
        return df

    logger.info(f"    Exploding {len(month_cols)} month columns "
                f"→ {value_col_name}")

    # ── Critical fix: cast ALL month columns to double first ──────────────
    # SQLite integer columns get inferred as BIGINT by Spark/Pandas.
    # stack() requires uniform types across all value columns.
    # Casting to double before stack eliminates the type mismatch.
    for col in month_cols:
        df = df.withColumn(col, F.col(col).cast("double"))

    # Build stack expression — all columns now guaranteed double
    stack_pairs = ", ".join(
        f"'{col}', `{col}`" for col in month_cols
    )
    stack_expr = (
        f"stack({len(month_cols)}, {stack_pairs}) "
        f"AS (month_label, {value_col_name})"
    )

    exploded = df.select(
        *[F.col(c) for c in non_month_cols],
        F.expr(stack_expr)
    )

    # Map month_label → month_key integer
    month_key_map = {
        label: month_label_to_key(label) for label in month_cols
    }
    mapping_expr = F.create_map(
        *[item for pair in
          [(F.lit(k), F.lit(v)) for k, v in month_key_map.items()]
          for item in pair]
    )

    exploded = exploded.withColumn(
        "month_key",
        mapping_expr[F.col("month_label")].cast(IntegerType())
    ).drop("month_label")

    # Cast value column to target type
    exploded = exploded.withColumn(
        value_col_name,
        F.col(value_col_name).cast(cast_type)
    )

    # Drop rows where month had no value (product inactive that month)
    exploded = exploded.filter(F.col(value_col_name).isNotNull())

    return exploded


def forward_fill(
    df: DataFrame,
    value_col: str,
    partition_cols: list[str],
    order_col: str = "month_key",
) -> DataFrame:
    """
    Forward fill null values within a partition ordered by month_key.
    Used for target_yield nulls (sensor dropout).
    """
    window = (
        Window
        .partitionBy(*partition_cols)
        .orderBy(order_col)
        .rowsBetween(Window.unboundedPreceding, 0)
    )
    filled_col = f"{value_col}_filled"
    df = df.withColumn(
        filled_col,
        F.last(F.col(value_col), ignorenulls=True).over(window)
    )
    df = df.withColumn(
        "is_forward_filled",
        F.col(value_col).isNull() & F.col(filled_col).isNotNull()
    )
    df = df.drop(value_col).withColumnRenamed(filled_col, value_col)
    return df


def add_silver_metadata(
    df: DataFrame,
    pipeline_run_id: str,
    ingestion_ts: str,
) -> DataFrame:
    """Add standard Silver metadata columns."""
    return (
        df
        .withColumn("pipeline_run_id", F.lit(pipeline_run_id))
        .withColumn("ingestion_ts", F.lit(ingestion_ts))
        .withColumn("is_valid", F.lit(True))
        .withColumn("invalid_reason", F.lit(None).cast(StringType()))
    )


def write_to_duckdb(
    df: DataFrame,
    table_name: str,
    duck_conn,
    partition_col: str = "",
    z_order_cols: list[str] = None,
) -> int:
    """
    Write Spark DataFrame to DuckDB table.
    Collects to Pandas first (local mode — data fits in memory).
    Returns row count written.
    """
    pandas_df = df.toPandas()
    duck_conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    duck_conn.register("_temp_silver", pandas_df)
    duck_conn.execute(f"""
        CREATE TABLE {table_name} AS
        SELECT * FROM _temp_silver
    """)
    duck_conn.unregister("_temp_silver")

    if partition_col and partition_col in pandas_df.columns:
        duck_conn.execute(f"""
            CREATE INDEX IF NOT EXISTS
            idx_{table_name}_{partition_col}
            ON {table_name} ({partition_col})
        """)

    if z_order_cols:
        for col in z_order_cols:
            if col in pandas_df.columns:
                duck_conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS
                    idx_{table_name}_{col}
                    ON {table_name} ({col})
                """)

    count = duck_conn.execute(
        f"SELECT COUNT(*) FROM {table_name}"
    ).fetchone()[0]
    return count