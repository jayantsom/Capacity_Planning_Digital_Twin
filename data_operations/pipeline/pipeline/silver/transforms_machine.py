"""
Silver transforms: Machine tables.
brnz_machine_execution  → slvr_machine_execution  (daily aggregated)
brnz_machine_test_param → slvr_machine_test_param (daily aggregated)
brnz_machine_logs       → slvr_machine_logs
"""

import hashlib

import pyspark.sql.functions as F

from capacity_twin_core.logging import logger
from data_operations.pipeline.pipeline.silver.utils import add_silver_metadata, md5_surrogate_key


def transform_machine_execution(duck_conn, spark, run_id: str, ts: str) -> int:
    logger.info("  slvr_machine_execution (chunked — large table)")

    # Process in monthly chunks to avoid memory pressure
    month_keys = duck_conn.execute("""
        SELECT DISTINCT month_key
        FROM brnz_machine_execution
        ORDER BY month_key
    """).fetchall()
    if not month_keys:
        duck_conn.execute(
            """
            CREATE OR REPLACE TABLE slvr_machine_execution AS
            SELECT
                factory_code, site_code, product_number, product_type,
                test_category_id, test_type, execution_date, month_key,
                CAST(passed_qty AS DOUBLE) AS passed_qty_sum,
                CAST(failed_qty AS DOUBLE) AS failed_qty_sum,
                CAST(total_qty AS DOUBLE) AS total_qty_sum,
                CAST(yield_avg AS DOUBLE) AS yield_avg,
                CAST(final_test_yield_avg AS DOUBLE) AS final_test_yield_avg,
                CAST(test_duration_avg_sec AS DOUBLE) AS test_duration_avg,
                CAST(handling_time_avg_sec AS DOUBLE) AS handling_time_avg,
                CAST(setup_time_avg_sec AS DOUBLE) AS setup_time_avg,
                CAST(load_unload_time_avg_sec AS DOUBLE) AS load_unload_time_avg,
                CAST(idle_time_avg_sec AS DOUBLE) AS idle_time_avg,
                CAST(retest_count_avg AS DOUBLE) AS retest_count_avg,
                CAST(equipment_downtime_avg_sec AS DOUBLE)
                    AS equipment_downtime_avg,
                CAST(actual_throughput_uph AS DOUBLE) AS actual_throughput,
                CAST(NULL AS BOOLEAN) AS qty_consistent,
                CAST(NULL AS VARCHAR) AS data_type,
                CAST(NULL AS VARCHAR) AS machine_exec_pk,
                CAST(NULL AS VARCHAR) AS pipeline_run_id,
                CAST(NULL AS VARCHAR) AS ingestion_ts,
                CAST(NULL AS BOOLEAN) AS is_valid,
                CAST(NULL AS VARCHAR) AS invalid_reason
            FROM brnz_machine_execution
            WHERE false
            """
        )
        duck_conn.execute(
            "CREATE INDEX idx_slvr_machine_exec_month ON slvr_machine_execution (month_key)"
        )
        duck_conn.execute(
            """
            CREATE INDEX idx_slvr_machine_exec_factory
            ON slvr_machine_execution (factory_code, test_category_id)
            """
        )
        return 0

    total_written = 0
    first = True

    for (mk,) in month_keys:
        chunk_pd = duck_conn.execute(f"""
            SELECT * FROM brnz_machine_execution
            WHERE month_key = {mk}
              AND is_valid = true
        """).df()

        if chunk_pd.empty:
            continue

        chunk_df = spark.createDataFrame(chunk_pd)

        # Aggregate to daily grain (deduplicate duplicates via mean)
        agg_df = chunk_df.groupBy(
            "factory_code",
            "site_code",
            "product_number",
            "product_type",
            "test_category_id",
            "test_type",
            "execution_date",
            "month_key",
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
            F.abs(F.col("passed_qty_sum") + F.col("failed_qty_sum") - F.col("total_qty_sum")) <= 1,
        )

        agg_df = agg_df.withColumn("data_type", F.lit("ACTUAL"))

        agg_df = md5_surrogate_key(
            agg_df,
            ["factory_code", "product_number", "test_category_id", "execution_date"],
            "machine_exec_pk",
        )
        agg_df = add_silver_metadata(agg_df, run_id, ts)

        # Write chunk
        chunk_pd_out = agg_df.toPandas()
        duck_conn.register("_temp_machine", chunk_pd_out)
        if first:
            duck_conn.execute("DROP TABLE IF EXISTS slvr_machine_execution")
            duck_conn.execute("""
                CREATE TABLE slvr_machine_execution AS
                SELECT * FROM _temp_machine
            """)
            first = False
        else:
            duck_conn.execute("""
                INSERT INTO slvr_machine_execution
                SELECT * FROM _temp_machine
            """)
        duck_conn.unregister("_temp_machine")
        total_written += len(chunk_pd_out)

    # Create indexes
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_slvr_machine_exec_month
        ON slvr_machine_execution (month_key)
    """)
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_slvr_machine_exec_factory
        ON slvr_machine_execution (factory_code, test_category_id)
    """)

    logger.info(f"    {total_written:,} rows")
    return total_written


def transform_machine_test_param(duck_conn, spark, run_id: str, ts: str) -> int:
    logger.info("  slvr_machine_test_param (chunked)")

    month_keys = duck_conn.execute("""
        SELECT DISTINCT month_key FROM brnz_machine_test_param
        ORDER BY month_key
    """).fetchall()
    if not month_keys:
        duck_conn.execute(
            """
            CREATE OR REPLACE TABLE slvr_machine_test_param AS
            SELECT
                factory_code, site_code, product_number, test_category_id,
                test_type, execution_date, month_key,
                CAST(first_pass_qty AS DOUBLE) AS first_pass_qty_sum,
                CAST(first_fail_qty AS DOUBLE) AS first_fail_qty_sum,
                CAST(total_qty AS DOUBLE) AS total_qty_sum,
                CAST(first_pass_yield AS DOUBLE) AS first_pass_yield,
                CAST(test_x_parameter AS DOUBLE) AS test_x_parameter,
                CAST(retest_times_avg AS DOUBLE) AS retest_times_avg,
                retest_times_type1,
                CAST(retest_times_type2 AS DOUBLE) AS retest_times_type2,
                CAST(yield_retest_1 AS DOUBLE) AS yield_retest_1,
                CAST(yield_retest_2_plus AS DOUBLE) AS yield_retest_2_plus,
                CAST(NULL AS VARCHAR) AS machine_param_pk,
                CAST(NULL AS VARCHAR) AS pipeline_run_id,
                CAST(NULL AS VARCHAR) AS ingestion_ts,
                CAST(NULL AS BOOLEAN) AS is_valid,
                CAST(NULL AS VARCHAR) AS invalid_reason
            FROM brnz_machine_test_param
            WHERE false
            """
        )
        duck_conn.execute(
            "CREATE INDEX idx_slvr_machine_param_month ON slvr_machine_test_param (month_key)"
        )
        return 0

    total_written = 0
    first = True

    for (mk,) in month_keys:
        chunk_pd = duck_conn.execute(f"""
            SELECT * FROM brnz_machine_test_param
            WHERE month_key = {mk} AND is_valid = true
        """).df()

        if chunk_pd.empty:
            continue

        chunk_df = spark.createDataFrame(chunk_pd)

        agg_df = chunk_df.groupBy(
            "factory_code",
            "site_code",
            "product_number",
            "test_category_id",
            "test_type",
            "execution_date",
            "month_key",
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
            ["factory_code", "product_number", "test_category_id", "execution_date"],
            "machine_param_pk",
        )
        agg_df = add_silver_metadata(agg_df, run_id, ts)

        chunk_pd_out = agg_df.toPandas()
        duck_conn.register("_temp_param", chunk_pd_out)
        if first:
            duck_conn.execute("DROP TABLE IF EXISTS slvr_machine_test_param")
            duck_conn.execute("""
                CREATE TABLE slvr_machine_test_param AS
                SELECT * FROM _temp_param
            """)
            first = False
        else:
            duck_conn.execute("""
                INSERT INTO slvr_machine_test_param SELECT * FROM _temp_param
            """)
        duck_conn.unregister("_temp_param")
        total_written += len(chunk_pd_out)

    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_slvr_machine_param_month
        ON slvr_machine_test_param (month_key)
    """)
    logger.info(f"    {total_written:,} rows")
    return total_written


def transform_machine_logs(duck_conn, spark, run_id: str, ts: str) -> int:
    logger.info("  slvr_machine_logs")

    logs_pd = duck_conn.execute("""
        SELECT * FROM brnz_machine_logs WHERE is_valid = true
    """).df()
    if logs_pd.empty:
        duck_conn.execute(
            """
            CREATE OR REPLACE TABLE slvr_machine_logs AS
            SELECT
                * EXCLUDE (
                    pipeline_run_id, ingestion_ts, is_valid, invalid_reason
                ),
                CAST(NULL AS VARCHAR) AS machine_log_pk,
                CAST(NULL AS VARCHAR) AS pipeline_run_id,
                CAST(NULL AS VARCHAR) AS ingestion_ts,
                CAST(NULL AS BOOLEAN) AS is_valid,
                CAST(NULL AS VARCHAR) AS invalid_reason
            FROM brnz_machine_logs
            WHERE false
            """
        )
        duck_conn.execute(
            "CREATE INDEX idx_slvr_machine_logs_month ON slvr_machine_logs (month_key)"
        )
        return 0

    logs_pd["machine_log_pk"] = logs_pd.apply(
        lambda r: hashlib.md5(
            f"{r['site_code']}|{r['factory_code']}|{r['product_number']}|"
            f"{r['test_category_id']}|{r['error_code']}|{r['log_ts']}".encode()
        ).hexdigest(),
        axis=1,
    )
    logs_pd["pipeline_run_id"] = run_id
    logs_pd["ingestion_ts"] = ts
    logs_pd["is_valid"] = True
    logs_pd["invalid_reason"] = None

    duck_conn.execute("DROP TABLE IF EXISTS slvr_machine_logs")
    duck_conn.register("_temp_logs", logs_pd)
    duck_conn.execute("""
        CREATE TABLE slvr_machine_logs AS SELECT * FROM _temp_logs
    """)
    duck_conn.unregister("_temp_logs")
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_slvr_machine_logs_month
        ON slvr_machine_logs (month_key)
    """)

    count = duck_conn.execute("SELECT COUNT(*) FROM slvr_machine_logs").fetchone()[0]
    logger.info(f"    {count:,} rows")
    return count
