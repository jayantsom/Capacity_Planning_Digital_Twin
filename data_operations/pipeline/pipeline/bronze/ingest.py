"""
Bronze layer ingestion engine.
Reads SQLite sources → validates → writes to DuckDB with metadata.
Uses DuckDB's native SQLite scanner (no JDBC, no Spark for this layer).
Bronze is lightweight enough that DuckDB handles it faster than Spark.
"""

import hashlib
import sqlite3
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime

import duckdb
import pandas as pd

from capacity_twin_core.domain.constants import (
    DATA_TYPE_ACTUAL,
    DATA_TYPE_FORECAST,
)
from capacity_twin_core.logging import logger
from capacity_twin_core.runtime.database_paths import (
    get_duckdb_connection,
    get_sqlite_path,
    load_config,
)
from data_operations.pipeline.pipeline.bronze.schema import BRONZE_CONFIGS, BronzeTableConfig

# ── Metadata helpers ───────────────────────────────────────────────────────────


def md5_key(*args) -> str:
    raw = "|".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()


def get_data_type(snapshot_date_str: str, month_col: str, actual_end: str) -> str:
    """Determine ACTUAL vs FORECAST based on month column label."""
    # month_col format: jan_2023, feb_2026, jul_2026 ...
    try:
        parts = month_col.split("_")
        month_abbr = parts[0]
        year = int(parts[1])
        month_map = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }
        month_num = month_map.get(month_abbr, 1)
        col_date = date(year, month_num, 1)
        cutoff = date.fromisoformat(actual_end)
        return DATA_TYPE_ACTUAL if col_date <= cutoff else DATA_TYPE_FORECAST
    except (IndexError, TypeError, ValueError):
        return DATA_TYPE_ACTUAL


# ── Validation ─────────────────────────────────────────────────────────────────


def validate_row(
    row: dict,
    config: BronzeTableConfig,
    *,
    actual_end: str = "2026-10-31",
) -> tuple[bool, str]:
    """
    Run Bronze validation rules B-VAL-01 through B-VAL-06.
    Returns (is_valid, invalid_reason).
    """
    reasons = []

    # B-VAL-01: Null natural keys
    for key in config.natural_keys:
        if key in row and (row[key] is None or str(row[key]).strip() == ""):
            reasons.append(f"NULL_PRIMARY_KEY:{key}")

    # B-VAL-03: Yield range [0, 1]
    for col in config.yield_columns:
        val = row.get(col)
        if val is not None:
            try:
                fval = float(val)
                if fval < 0 or fval > 1:
                    reasons.append(f"YIELD_OUT_OF_RANGE:{col}={fval:.4f}")
            except (TypeError, ValueError):
                pass

    # B-VAL-04: Quantity non-negative
    for col in config.qty_columns:
        val = row.get(col)
        if val is not None:
            try:
                if float(val) < 0:
                    reasons.append(f"NEGATIVE_QUANTITY:{col}={val}")
            except (TypeError, ValueError):
                pass

    # B-VAL-09: Date range for Machine tables
    if config.is_machine:
        for col in config.date_columns:
            val = row.get(col)
            if val is not None:
                try:
                    d = date.fromisoformat(str(val)[:10])
                    if d < date(2023, 1, 1) or d > date.fromisoformat(actual_end):
                        reasons.append(f"DATE_OUT_OF_RANGE:{col}={val}")
                except ValueError:
                    reasons.append(f"INVALID_DATE:{col}={val}")

    is_valid = len(reasons) == 0
    return is_valid, "; ".join(reasons) if reasons else ""


def iter_sqlite_chunks(
    connection: sqlite3.Connection,
    table_name: str,
    chunk_size: int,
) -> Iterator[pd.DataFrame]:
    """Read immutable SQLite rowids with stable keyset pagination."""
    last_rowid = 0
    while True:
        chunk = pd.read_sql_query(
            f"""
            SELECT rowid AS _source_rowid, *
            FROM "{table_name}"
            WHERE rowid > ?
            ORDER BY rowid
            LIMIT ?
            """,
            connection,
            params=(last_rowid, chunk_size),
        )
        if chunk.empty:
            return
        yield chunk
        last_rowid = int(chunk["_source_rowid"].iloc[-1])


def _mark_duplicates(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    natural_keys: list[str],
) -> None:
    """Keep the first source row and explicitly reject later key duplicates."""
    columns = {
        row[1] for row in connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    }
    keys = [key for key in natural_keys if key in columns]
    if not keys:
        keys = ["_source_rowid"]
    partition = ", ".join(f'"{key}"' for key in keys)
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE _bronze_ranked AS
        SELECT
            * EXCLUDE (is_valid, invalid_reason),
            is_valid AND duplicate_rank = 1 AS is_valid,
            CASE
                WHEN duplicate_rank > 1 AND invalid_reason IS NOT NULL
                    THEN CAST(invalid_reason AS VARCHAR) || '; DUPLICATE_NATURAL_KEY'
                WHEN duplicate_rank > 1 THEN 'DUPLICATE_NATURAL_KEY'
                ELSE CAST(invalid_reason AS VARCHAR)
            END AS invalid_reason,
            duplicate_rank > 1 AS is_duplicate
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY {partition}
                    ORDER BY _source_rowid
                ) AS duplicate_rank
            FROM "{table_name}"
        )
        """
    )
    connection.execute(f'DROP TABLE "{table_name}"')
    connection.execute(f'ALTER TABLE _bronze_ranked RENAME TO "{table_name}"')


# ── Core ingestion function ────────────────────────────────────────────────────


def ingest_table(
    config: BronzeTableConfig,
    db_config: dict,
    duck_conn: duckdb.DuckDBPyConnection,
    pipeline_run_id: str,
    ingestion_ts: str,
) -> dict:
    """
    Ingest one source table from SQLite into DuckDB Bronze.
    Returns summary stats dict.
    """
    logger.info(f"  Ingesting: {config.source_table} → {config.bronze_table}")

    # ── Read from SQLite ───────────────────────────────────────────────────
    sqlite_path = get_sqlite_path(db_config["databases"]["raw"][config.source_db], db_config)
    with sqlite3.connect(sqlite_path) as src_conn:
        src_conn.row_factory = sqlite3.Row
        raw_df = pd.read_sql_query(
            f'SELECT rowid AS _source_rowid, * FROM "{config.source_table}" ORDER BY rowid',
            src_conn,
        )

    logger.info(f"    Read {len(raw_df):,} rows from {sqlite_path.name}")

    # ── Add Bronze metadata columns ────────────────────────────────────────
    rows_out = []
    total_valid = 0
    total_invalid = 0

    for _, row in raw_df.iterrows():
        row_dict = dict(row)

        # Generate bronze_id from natural keys
        nk_values = [str(row_dict.get(k, "")) for k in config.natural_keys]
        bronze_id = md5_key(
            config.source_db,
            config.source_table,
            row_dict.get("_source_rowid"),
            *nk_values,
        )

        # Validate
        is_valid, invalid_reason = validate_row(
            row_dict,
            config,
            actual_end=db_config["data_generation"]["end_date_actual"],
        )

        # Snapshot / forecast metadata
        snapshot_date = row_dict.get("snapshot_date", "")
        actual_end = db_config["data_generation"]["end_date_actual"]
        data_type = (
            DATA_TYPE_ACTUAL
            if config.is_machine
            else (DATA_TYPE_FORECAST if snapshot_date > actual_end else DATA_TYPE_ACTUAL)
        )

        # Build output row
        out = {**row_dict}
        out["bronze_id"] = bronze_id
        out["src_system"] = config.source_db
        out["ingestion_ts"] = ingestion_ts
        out["pipeline_run_id"] = pipeline_run_id
        out["is_valid"] = is_valid
        out["invalid_reason"] = invalid_reason if invalid_reason else None
        out["data_type"] = DATA_TYPE_ACTUAL if config.is_machine else data_type

        if is_valid:
            total_valid += 1
        else:
            total_invalid += 1

        rows_out.append(out)

    out_df = pd.DataFrame(rows_out)
    if out_df.empty:
        out_df = raw_df.copy()
        for column in (
            "bronze_id",
            "src_system",
            "ingestion_ts",
            "pipeline_run_id",
            "invalid_reason",
            "data_type",
        ):
            out_df[column] = pd.Series(dtype="string")
        out_df["is_valid"] = pd.Series(dtype="bool")

    # ── Write to DuckDB ────────────────────────────────────────────────────
    # Drop and recreate table for idempotent runs
    duck_conn.execute(f"DROP TABLE IF EXISTS {config.bronze_table}")
    duck_conn.register("_temp_bronze", out_df)
    duck_conn.execute(f"""
        CREATE TABLE {config.bronze_table} AS
        SELECT * FROM _temp_bronze
    """)
    duck_conn.unregister("_temp_bronze")
    _mark_duplicates(duck_conn, config.bronze_table, config.natural_keys)

    # Create partition index if applicable
    if config.partition_col and config.partition_col in out_df.columns:
        duck_conn.execute(f"""
            CREATE INDEX IF NOT EXISTS
            idx_{config.bronze_table}_{config.partition_col}
            ON {config.bronze_table} ({config.partition_col})
        """)

    row_count = duck_conn.execute(f"SELECT COUNT(*) FROM {config.bronze_table}").fetchone()[0]
    duplicate_count = duck_conn.execute(
        f"SELECT COUNT(*) FROM {config.bronze_table} WHERE is_duplicate"
    ).fetchone()[0]
    total_valid = duck_conn.execute(
        f"SELECT COUNT(*) FROM {config.bronze_table} WHERE is_valid"
    ).fetchone()[0]
    total_invalid = row_count - total_valid

    invalid_pct = (total_invalid / len(raw_df) * 100) if len(raw_df) > 0 else 0
    logger.info(
        f"    Written: {row_count:,} rows | "
        f"valid: {total_valid:,} | "
        f"invalid: {total_invalid:,} ({invalid_pct:.2f}%)"
    )

    return {
        "table": config.bronze_table,
        "rows_read": len(raw_df),
        "rows_written": row_count,
        "valid": total_valid,
        "invalid": total_invalid,
        "duplicates": duplicate_count,
        "invalid_pct": invalid_pct,
    }


# ── Machine tables: chunked ingestion ───────────────────────────────────────────────


def ingest_machine_table(
    config: BronzeTableConfig,
    db_config: dict,
    duck_conn: duckdb.DuckDBPyConnection,
    pipeline_run_id: str,
    ingestion_ts: str,
    chunk_size: int = 100_000,
) -> dict:
    """
    Chunked ingestion for large Machine tables (1M+ rows).
    Reads SQLite in chunks to avoid memory pressure.
    """
    logger.info(f"  Ingesting (chunked): {config.source_table} → {config.bronze_table}")

    sqlite_path = get_sqlite_path(db_config["databases"]["raw"][config.source_db], db_config)

    # Get total count first
    with sqlite3.connect(sqlite_path) as src_conn:
        total_rows = src_conn.execute(f"SELECT COUNT(*) FROM {config.source_table}").fetchone()[0]
    logger.info(f"    Source rows: {total_rows:,}")

    rows_written = 0
    total_valid = 0
    total_invalid = 0
    first_chunk = True
    last_source_rowid = 0

    with sqlite3.connect(sqlite_path) as src_conn:
        chunks = iter_sqlite_chunks(src_conn, config.source_table, chunk_size)
        for chunk_df in chunks:
            last_source_rowid = int(chunk_df["_source_rowid"].iloc[-1])

            # Add metadata
            chunk_out = []
            for _, row in chunk_df.iterrows():
                row_dict = dict(row)
                nk_values = [str(row_dict.get(k, "")) for k in config.natural_keys]
                bronze_id = md5_key(
                    config.source_db,
                    config.source_table,
                    row_dict.get("_source_rowid"),
                    *nk_values,
                )
                is_valid, invalid_reason = validate_row(
                    row_dict,
                    config,
                    actual_end=db_config["data_generation"]["end_date_actual"],
                )

                row_dict["bronze_id"] = bronze_id
                row_dict["src_system"] = config.source_db
                row_dict["ingestion_ts"] = ingestion_ts
                row_dict["pipeline_run_id"] = pipeline_run_id
                row_dict["is_valid"] = is_valid
                row_dict["invalid_reason"] = invalid_reason or None
                row_dict["data_type"] = DATA_TYPE_ACTUAL

                chunk_out.append(row_dict)
                if is_valid:
                    total_valid += 1
                else:
                    total_invalid += 1

            out_df = pd.DataFrame(chunk_out)

            # Write chunk
            duck_conn.register("_temp_chunk", out_df)
            if first_chunk:
                duck_conn.execute(f"DROP TABLE IF EXISTS {config.bronze_table}")
                duck_conn.execute(f"""
                    CREATE TABLE {config.bronze_table} AS
                    SELECT * FROM _temp_chunk
                """)
                first_chunk = False
            else:
                duck_conn.execute(f"""
                    INSERT INTO {config.bronze_table}
                    SELECT * FROM _temp_chunk
                """)
            duck_conn.unregister("_temp_chunk")
            rows_written += len(out_df)
            logger.info(
                f"    Source rowid {last_source_rowid:,}: {rows_written:,} rows written so far"
            )

    if first_chunk:
        with sqlite3.connect(sqlite_path) as src_conn:
            empty_df = pd.read_sql_query(
                f'SELECT rowid AS _source_rowid, * FROM "{config.source_table}" WHERE 1 = 0',
                src_conn,
            )
        for column in (
            "bronze_id",
            "src_system",
            "ingestion_ts",
            "pipeline_run_id",
            "invalid_reason",
            "data_type",
        ):
            empty_df[column] = pd.Series(dtype="string")
        empty_df["is_valid"] = pd.Series(dtype="bool")
        duck_conn.register("_temp_chunk", empty_df)
        duck_conn.execute(f"CREATE TABLE {config.bronze_table} AS SELECT * FROM _temp_chunk")
        duck_conn.unregister("_temp_chunk")

    _mark_duplicates(duck_conn, config.bronze_table, config.natural_keys)
    rows_written = duck_conn.execute(f"SELECT COUNT(*) FROM {config.bronze_table}").fetchone()[0]
    total_valid = duck_conn.execute(
        f"SELECT COUNT(*) FROM {config.bronze_table} WHERE is_valid"
    ).fetchone()[0]
    total_invalid = rows_written - total_valid
    duplicate_count = duck_conn.execute(
        f"SELECT COUNT(*) FROM {config.bronze_table} WHERE is_duplicate"
    ).fetchone()[0]

    # Create partition index
    columns = {
        row[1]
        for row in duck_conn.execute(f'PRAGMA table_info("{config.bronze_table}")').fetchall()
    }
    if config.partition_col and config.partition_col in columns:
        duck_conn.execute(f"""
            CREATE INDEX IF NOT EXISTS
            idx_{config.bronze_table}_{config.partition_col}
            ON {config.bronze_table} ({config.partition_col})
        """)

    invalid_pct = (total_invalid / total_rows * 100) if total_rows > 0 else 0
    logger.info(
        f"    Final: {rows_written:,} rows | "
        f"valid: {total_valid:,} | "
        f"invalid: {total_invalid:,} ({invalid_pct:.2f}%)"
    )

    return {
        "table": config.bronze_table,
        "rows_read": total_rows,
        "rows_written": rows_written,
        "valid": total_valid,
        "invalid": total_invalid,
        "duplicates": duplicate_count,
        "invalid_pct": invalid_pct,
    }


# ── Master Bronze runner ───────────────────────────────────────────────────────


def run_bronze_ingestion(
    config: dict,
    *,
    duck_conn: duckdb.DuckDBPyConnection | None = None,
    pipeline_run_id: str | None = None,
) -> list[dict]:
    """
    Run full Bronze ingestion for all source tables.
    Returns list of summary dicts for reporting.
    """
    import time

    start = time.time()

    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║              BRONZE LAYER — INGESTION                   ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")

    pipeline_run_id = pipeline_run_id or str(uuid.uuid4())
    ingestion_ts = datetime.now(UTC).isoformat()

    logger.info(f"  Pipeline run ID: {pipeline_run_id}")
    logger.info(f"  Ingestion timestamp: {ingestion_ts}")

    owns_connection = duck_conn is None
    duck_conn = duck_conn or get_duckdb_connection(config, database_key="bronze")
    summaries = []

    # Large Machine tables use chunked ingestion
    machine_tables = {"brnz_machine_execution", "brnz_machine_test_param", "brnz_machine_logs"}
    chunk_size = int(config.get("publication", {}).get("bronze_chunk_size", 100_000))

    for table_config in BRONZE_CONFIGS:
        logger.info(f"\n── {table_config.bronze_table} ─────────────────")
        try:
            if table_config.bronze_table in machine_tables:
                summary = ingest_machine_table(
                    table_config, config, duck_conn, pipeline_run_id, ingestion_ts, chunk_size
                )
            else:
                summary = ingest_table(
                    table_config, config, duck_conn, pipeline_run_id, ingestion_ts
                )
            summaries.append(summary)
        except Exception as e:
            logger.error(f"  FAILED: {table_config.bronze_table}: {e}")
            raise

    # ── Print summary report ───────────────────────────────────────────────
    elapsed = time.time() - start
    logger.info("\n╔══════════════════════════════════════════════════════════╗")
    logger.info("║                  BRONZE SUMMARY                         ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    logger.info(f"  {'Table':<35} {'Rows':>10} {'Valid':>10} {'Invalid':>10} {'Inv%':>6}")
    logger.info(f"  {'-' * 75}")
    total_rows = 0
    for s in summaries:
        logger.info(
            f"  {s['table']:<35} {s['rows_written']:>10,} "
            f"{s['valid']:>10,} {s['invalid']:>10,} "
            f"{s['invalid_pct']:>5.2f}%"
        )
        total_rows += s["rows_written"]
    logger.info(f"  {'-' * 75}")
    logger.info(f"  {'TOTAL':<35} {total_rows:>10,}")
    logger.info(f"\n  Wall time: {elapsed:.1f}s")
    logger.success("Bronze ingestion complete.")

    if owns_connection:
        duck_conn.close()
    return summaries


if __name__ == "__main__":
    cfg = load_config()
    run_bronze_ingestion(cfg)
