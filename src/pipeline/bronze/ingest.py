"""
Bronze layer ingestion engine.
Reads SQLite sources → validates → writes to DuckDB with metadata.
Uses DuckDB's native SQLite scanner (no JDBC, no Spark for this layer).
Bronze is lightweight enough that DuckDB handles it faster than Spark.
"""

import hashlib
import sqlite3
import uuid
from datetime import datetime, date
from pathlib import Path

import duckdb
import pandas as pd
import numpy as np

from config.constants import (
    DATA_TYPE_ACTUAL, DATA_TYPE_FORECAST,
    FORECAST_SOURCE_PLANNER,
    ACTUAL_END,
)
from src.pipeline.bronze.schema import BRONZE_CONFIGS, BronzeTableConfig
from src.utils.db_utils import load_config, get_sqlite_path, get_duckdb_connection
from src.utils.logger import logger


# ── Metadata helpers ───────────────────────────────────────────────────────────

def md5_key(*args) -> str:
    raw = "|".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()


def get_pipeline_run_id() -> str:
    return str(uuid.uuid4())


def get_data_type(snapshot_date_str: str, month_col: str) -> str:
    """Determine ACTUAL vs FORECAST based on month column label."""
    # month_col format: jan_2023, feb_2026, jul_2026 ...
    try:
        parts = month_col.split("_")
        month_abbr = parts[0]
        year = int(parts[1])
        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4,
            "may": 5, "jun": 6, "jul": 7, "aug": 8,
            "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        month_num = month_map.get(month_abbr, 1)
        col_date = date(year, month_num, 1)
        cutoff = date(2026, 6, 30)
        return DATA_TYPE_ACTUAL if col_date <= cutoff else DATA_TYPE_FORECAST
    except Exception:
        return DATA_TYPE_ACTUAL


# ── Validation ─────────────────────────────────────────────────────────────────

def validate_row(row: dict, config: BronzeTableConfig) -> tuple[bool, str]:
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

    # B-VAL-09: Date range for MI tables
    if config.is_mi:
        for col in config.date_columns:
            val = row.get(col)
            if val is not None:
                try:
                    d = date.fromisoformat(str(val)[:10])
                    if d < date(2023, 1, 1) or d > date(2026, 6, 30):
                        reasons.append(f"DATE_OUT_OF_RANGE:{col}={val}")
                except ValueError:
                    reasons.append(f"INVALID_DATE:{col}={val}")

    is_valid = len(reasons) == 0
    return is_valid, "; ".join(reasons) if reasons else ""


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
    sqlite_path = get_sqlite_path(
        db_config["databases"]["raw"][config.source_db], db_config
    )
    with sqlite3.connect(sqlite_path) as src_conn:
        src_conn.row_factory = sqlite3.Row
        raw_df = pd.read_sql_query(
            f"SELECT * FROM {config.source_table}", src_conn
        )

    logger.info(f"    Read {len(raw_df):,} rows from {sqlite_path.name}")

    # ── Detect month columns (horizontal format) ───────────────────────────
    import re
    month_pattern = re.compile(r"^[a-z]{3}_\d{4}$")
    month_cols = [c for c in raw_df.columns if month_pattern.match(c)]
    non_month_cols = [c for c in raw_df.columns if not month_pattern.match(c)]

    # ── Add Bronze metadata columns ────────────────────────────────────────
    rows_out = []
    total_valid = 0
    total_invalid = 0

    for _, row in raw_df.iterrows():
        row_dict = dict(row)

        # Generate bronze_id from natural keys
        nk_values = [str(row_dict.get(k, "")) for k in config.natural_keys]
        bronze_id = md5_key(*nk_values, ingestion_ts)

        # Validate
        is_valid, invalid_reason = validate_row(row_dict, config)

        # Snapshot / forecast metadata
        snapshot_id     = row_dict.get("snapshot_id", "")
        snapshot_date   = row_dict.get("snapshot_date", "")
        forecast_source = row_dict.get("forecast_source", FORECAST_SOURCE_PLANNER)
        data_type       = DATA_TYPE_ACTUAL if config.is_mi else (
            DATA_TYPE_FORECAST
            if snapshot_date > "2026-06-30"
            else DATA_TYPE_ACTUAL
        )

        # Build output row
        out = {**row_dict}
        out["bronze_id"]        = bronze_id
        out["src_system"]       = config.source_db
        out["ingestion_ts"]     = ingestion_ts
        out["pipeline_run_id"]  = pipeline_run_id
        out["is_valid"]         = is_valid
        out["invalid_reason"]   = invalid_reason if invalid_reason else None
        out["data_type"]        = DATA_TYPE_ACTUAL if config.is_mi else data_type

        if is_valid:
            total_valid += 1
        else:
            total_invalid += 1

        rows_out.append(out)

    out_df = pd.DataFrame(rows_out)

    # ── Write to DuckDB ────────────────────────────────────────────────────
    # Drop and recreate table for idempotent runs
    duck_conn.execute(f"DROP TABLE IF EXISTS {config.bronze_table}")
    duck_conn.register("_temp_bronze", out_df)
    duck_conn.execute(f"""
        CREATE TABLE {config.bronze_table} AS
        SELECT * FROM _temp_bronze
    """)
    duck_conn.unregister("_temp_bronze")

    # Create partition index if applicable
    if config.partition_col and config.partition_col in out_df.columns:
        duck_conn.execute(f"""
            CREATE INDEX IF NOT EXISTS
            idx_{config.bronze_table}_{config.partition_col}
            ON {config.bronze_table} ({config.partition_col})
        """)

    row_count = duck_conn.execute(
        f"SELECT COUNT(*) FROM {config.bronze_table}"
    ).fetchone()[0]

    invalid_pct = (total_invalid / len(raw_df) * 100) if len(raw_df) > 0 else 0
    logger.info(f"    Written: {row_count:,} rows | "
                f"valid: {total_valid:,} | "
                f"invalid: {total_invalid:,} ({invalid_pct:.2f}%)")

    return {
        "table":          config.bronze_table,
        "rows_read":      len(raw_df),
        "rows_written":   row_count,
        "valid":          total_valid,
        "invalid":        total_invalid,
        "invalid_pct":    invalid_pct,
    }


# ── MI tables: chunked ingestion ───────────────────────────────────────────────

def ingest_mi_table(
    config: BronzeTableConfig,
    db_config: dict,
    duck_conn: duckdb.DuckDBPyConnection,
    pipeline_run_id: str,
    ingestion_ts: str,
    chunk_size: int = 100_000,
) -> dict:
    """
    Chunked ingestion for large MI tables (1M+ rows).
    Reads SQLite in chunks to avoid memory pressure.
    """
    logger.info(f"  Ingesting (chunked): {config.source_table} "
                f"→ {config.bronze_table}")

    sqlite_path = get_sqlite_path(
        db_config["databases"]["raw"][config.source_db], db_config
    )

    # Get total count first
    with sqlite3.connect(sqlite_path) as src_conn:
        total_rows = src_conn.execute(
            f"SELECT COUNT(*) FROM {config.source_table}"
        ).fetchone()[0]
    logger.info(f"    Source rows: {total_rows:,}")

    rows_written = 0
    total_valid = 0
    total_invalid = 0
    first_chunk = True
    offset = 0

    while offset < total_rows:
        with sqlite3.connect(sqlite_path) as src_conn:
            chunk_df = pd.read_sql_query(
                f"SELECT * FROM {config.source_table} "
                f"LIMIT {chunk_size} OFFSET {offset}",
                src_conn
            )

        if chunk_df.empty:
            break

        # Add metadata
        chunk_out = []
        for _, row in chunk_df.iterrows():
            row_dict = dict(row)
            nk_values = [str(row_dict.get(k, "")) for k in config.natural_keys]
            bronze_id = md5_key(*nk_values, ingestion_ts)
            is_valid, invalid_reason = validate_row(row_dict, config)

            row_dict["bronze_id"]       = bronze_id
            row_dict["src_system"]      = config.source_db
            row_dict["ingestion_ts"]    = ingestion_ts
            row_dict["pipeline_run_id"] = pipeline_run_id
            row_dict["is_valid"]        = is_valid
            row_dict["invalid_reason"]  = invalid_reason or None
            row_dict["data_type"]       = DATA_TYPE_ACTUAL

            chunk_out.append(row_dict)
            if is_valid:
                total_valid += 1
            else:
                total_invalid += 1

        out_df = pd.DataFrame(chunk_out)

        # Write chunk
        if first_chunk:
            duck_conn.execute(f"DROP TABLE IF EXISTS {config.bronze_table}")
            duck_conn.register("_temp_chunk", out_df)
            duck_conn.execute(f"""
                CREATE TABLE {config.bronze_table} AS
                SELECT * FROM _temp_chunk
            """)
            duck_conn.unregister("_temp_chunk")
            first_chunk = False
        else:
            duck_conn.register("_temp_chunk", out_df)
            duck_conn.execute(f"""
                INSERT INTO {config.bronze_table}
                SELECT * FROM _temp_chunk
            """)
            duck_conn.unregister("_temp_chunk")

        rows_written += len(out_df)
        offset += chunk_size
        logger.info(f"    Chunk offset {offset:,}: "
                    f"{rows_written:,} rows written so far")

    # Create partition index
    if config.partition_col and config.partition_col in out_df.columns:
        duck_conn.execute(f"""
            CREATE INDEX IF NOT EXISTS
            idx_{config.bronze_table}_{config.partition_col}
            ON {config.bronze_table} ({config.partition_col})
        """)

    invalid_pct = (total_invalid / total_rows * 100) if total_rows > 0 else 0
    logger.info(f"    Final: {rows_written:,} rows | "
                f"valid: {total_valid:,} | "
                f"invalid: {total_invalid:,} ({invalid_pct:.2f}%)")

    return {
        "table":        config.bronze_table,
        "rows_read":    total_rows,
        "rows_written": rows_written,
        "valid":        total_valid,
        "invalid":      total_invalid,
        "invalid_pct":  invalid_pct,
    }


# ── Master Bronze runner ───────────────────────────────────────────────────────

def run_bronze_ingestion(config: dict) -> list[dict]:
    """
    Run full Bronze ingestion for all source tables.
    Returns list of summary dicts for reporting.
    """
    import time
    start = time.time()

    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║              BRONZE LAYER — INGESTION                   ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")

    pipeline_run_id = get_pipeline_run_id()
    ingestion_ts    = datetime.utcnow().isoformat()

    logger.info(f"  Pipeline run ID: {pipeline_run_id}")
    logger.info(f"  Ingestion timestamp: {ingestion_ts}")

    duck_conn = get_duckdb_connection(config)
    summaries = []

    # Large MI tables use chunked ingestion
    mi_tables = {"brnz_mi_execution", "brnz_mi_test_param", "brnz_mi_logs"}

    for table_config in BRONZE_CONFIGS:
        logger.info(f"\n── {table_config.bronze_table} ─────────────────")
        try:
            if table_config.bronze_table in mi_tables:
                summary = ingest_mi_table(
                    table_config, config, duck_conn,
                    pipeline_run_id, ingestion_ts
                )
            else:
                summary = ingest_table(
                    table_config, config, duck_conn,
                    pipeline_run_id, ingestion_ts
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
    logger.info(f"  {'Table':<35} {'Rows':>10} {'Valid':>10} "
                f"{'Invalid':>10} {'Inv%':>6}")
    logger.info(f"  {'-'*75}")
    total_rows = 0
    for s in summaries:
        logger.info(f"  {s['table']:<35} {s['rows_written']:>10,} "
                    f"{s['valid']:>10,} {s['invalid']:>10,} "
                    f"{s['invalid_pct']:>5.2f}%")
        total_rows += s["rows_written"]
    logger.info(f"  {'-'*75}")
    logger.info(f"  {'TOTAL':<35} {total_rows:>10,}")
    logger.info(f"\n  Wall time: {elapsed:.1f}s")
    logger.success("Bronze ingestion complete.")

    duck_conn.close()
    return summaries


if __name__ == "__main__":
    cfg = load_config()
    run_bronze_ingestion(cfg)