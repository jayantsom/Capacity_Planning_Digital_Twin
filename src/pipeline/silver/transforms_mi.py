"""
Silver transforms: Manufacturing Intelligence tables.
brnz_mi_execution  → slvr_mi_execution  (daily aggregated)
brnz_mi_test_param → slvr_mi_test_param (daily aggregated)
brnz_mi_logs       → slvr_mi_logs
"""

import hashlib
import pandas as pd
import pyspark.sql.functions as F
from pyspark.sql.types import StringType

from src.pipeline.silver.utils import (
    md5_surrogate_key, add_silver_metadata, write_to_duckdb
)
from src.utils.logger import logger


def transform_mi_execution(duck_conn, spark, run_id: str, ts: str) -> int:
    logger.info("  slvr_mi_execution (chunked — large table)")

    # Process in monthly chunks to avoid memory pressure
    month_keys = duck_conn.execute("""
        SELECT DISTINCT month_key
        FROM brnz_mi_execution
        ORDER BY month_key
    """).fetchall()

    total_written = 0
    first = True

    for (mk,) in month_keys:
        chunk_pd = duck_conn.execute(f"""
            SELECT * FROM brnz_mi_execution
            WHERE month_key = {mk}
              AND is_valid = true
        """).df()

        if chunk_pd.empty:
            continue

        chunk_df = spark.createDataFrame(chunk_pd)

        # Aggregate to daily grain (deduplicate duplicates via mean)
        agg_df = chunk_df.groupBy(
            "factory_code", "site_code", "product_number",
            "product_type", "test_category_id", "test_type",
            "execution_date", "month_key"
        ).agg(
            F.sum("passed_qty").alias("passed_qty_sum"),
            F.sum("failed_qty").alias("failed_qty_sum"),
            F.sum("total_qty").alias("total_qty_sum"),
            F.mean("yield_avg").alias("yield_avg"),
            F.mean("final_test_yield_avg").alias("final_test_yield_avg"),
            F.mean("test_duration_avg_sec").alias("test_duration_avg"),
            F.mean("handling_time_avg_sec").alias("handling_time_avg"),
            F.mean("setup_time_avg_sec").alias("setup_time_avg"),
            F.mean("load_unload_time_avg_sec").alias("load_unload_time_avg"),
            F.mean("idle_time_avg_sec").alias("idle_time_avg"),
            F.mean("retest_count_avg").alias("retest_count_avg"),
            F.mean("equipment_downtime_avg_sec").alias("equipment_downtime_avg"),
            F.mean("actual_throughput_uph").alias("actual_throughput"),
        )

        # Quantity consistency check
        agg_df = agg_df.withColumn(
            "qty_consistent",
            F.abs(
                F.col("passed_qty_sum") + F.col("failed_qty_sum")
                - F.col("total_qty_sum")
            ) <= 1
        )

        agg_df = agg_df.withColumn("data_type", F.lit("ACTUAL"))

        agg_df = md5_surrogate_key(
            agg_df,
            ["factory_code", "product_number",
             "test_category_id", "execution_date"],
            "mi_exec_pk"
        )
        agg_df = add_silver_metadata(agg_df, run_id, ts)

        # Write chunk
        chunk_pd_out = agg_df.toPandas()
        duck_conn.register("_temp_mi", chunk_pd_out)
        if first:
            duck_conn.execute("DROP TABLE IF EXISTS slvr_mi_execution")
            duck_conn.execute("""
                CREATE TABLE slvr_mi_execution AS
                SELECT * FROM _temp_mi
            """)
            first = False
        else:
            duck_conn.execute("""
                INSERT INTO slvr_mi_execution
                SELECT * FROM _temp_mi
            """)
        duck_conn.unregister("_temp_mi")
        total_written += len(chunk_pd_out)

    # Create indexes
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_slvr_mi_exec_month
        ON slvr_mi_execution (month_key)
    """)
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_slvr_mi_exec_factory
        ON slvr_mi_execution (factory_code, test_category_id)
    """)

    logger.info(f"    {total_written:,} rows")
    return total_written


def transform_mi_test_param(duck_conn, spark, run_id: str, ts: str) -> int:
    logger.info("  slvr_mi_test_param (chunked)")

    month_keys = duck_conn.execute("""
        SELECT DISTINCT month_key FROM brnz_mi_test_param
        ORDER BY month_key
    """).fetchall()

    total_written = 0
    first = True

    for (mk,) in month_keys:
        chunk_pd = duck_conn.execute(f"""
            SELECT * FROM brnz_mi_test_param
            WHERE month_key = {mk} AND is_valid = true
        """).df()

        if chunk_pd.empty:
            continue

        chunk_df = spark.createDataFrame(chunk_pd)

        agg_df = chunk_df.groupBy(
            "factory_code", "site_code", "product_number",
            "test_category_id", "test_type",
            "execution_date", "month_key"
        ).agg(
            F.sum("first_pass_qty").alias("first_pass_qty_sum"),
            F.sum("first_fail_qty").alias("first_fail_qty_sum"),
            F.sum("total_qty").alias("total_qty_sum"),
            F.mean("first_pass_yield").alias("first_pass_yield"),
            F.mean("test_x_parameter").alias("test_x_parameter"),
            F.mean("retest_times_avg").alias("retest_times_avg"),
            F.first("retest_times_type1").alias("retest_times_type1"),
            F.mean("retest_times_type2").alias("retest_times_type2"),
            F.mean("yield_retest_1").alias("yield_retest_1"),
            F.mean("yield_retest_2_plus").alias("yield_retest_2_plus"),
        )

        agg_df = md5_surrogate_key(
            agg_df,
            ["factory_code", "product_number",
             "test_category_id", "execution_date"],
            "mi_param_pk"
        )
        agg_df = add_silver_metadata(agg_df, run_id, ts)

        chunk_pd_out = agg_df.toPandas()
        duck_conn.register("_temp_param", chunk_pd_out)
        if first:
            duck_conn.execute("DROP TABLE IF EXISTS slvr_mi_test_param")
            duck_conn.execute("""
                CREATE TABLE slvr_mi_test_param AS
                SELECT * FROM _temp_param
            """)
            first = False
        else:
            duck_conn.execute("""
                INSERT INTO slvr_mi_test_param SELECT * FROM _temp_param
            """)
        duck_conn.unregister("_temp_param")
        total_written += len(chunk_pd_out)

    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_slvr_mi_param_month
        ON slvr_mi_test_param (month_key)
    """)
    logger.info(f"    {total_written:,} rows")
    return total_written


def transform_mi_logs(duck_conn, spark, run_id: str, ts: str) -> int:
    logger.info("  slvr_mi_logs")

    logs_pd = duck_conn.execute("""
        SELECT * FROM brnz_mi_logs WHERE is_valid = true
    """).df()

    import hashlib
    logs_pd["mi_log_pk"] = logs_pd.apply(
        lambda r: hashlib.md5(
            f"{r['product_number']}|{r['test_category_id']}|"
            f"{r['error_code']}|{r['log_ts']}".encode()
        ).hexdigest(), axis=1
    )
    logs_pd["pipeline_run_id"] = run_id
    logs_pd["ingestion_ts"]    = ts
    logs_pd["is_valid"]        = True
    logs_pd["invalid_reason"]  = None

    duck_conn.execute("DROP TABLE IF EXISTS slvr_mi_logs")
    duck_conn.register("_temp_logs", logs_pd)
    duck_conn.execute("""
        CREATE TABLE slvr_mi_logs AS SELECT * FROM _temp_logs
    """)
    duck_conn.unregister("_temp_logs")
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_slvr_mi_logs_month
        ON slvr_mi_logs (month_key)
    """)

    count = duck_conn.execute(
        "SELECT COUNT(*) FROM slvr_mi_logs"
    ).fetchone()[0]
    logger.info(f"    {count:,} rows")
    return count