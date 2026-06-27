"""
Silver transforms: planning tables.
Explodes horizontal month columns → row-per-month format.
brnz_dmnd_forecast   → slvr_dmnd_forecast
brnz_tgt_test_time   → slvr_tgt_test_time
brnz_tgt_yield       → slvr_tgt_yield
brnz_site_equip_inv  → slvr_site_equip_inv
brnz_site_soft       → slvr_site_soft
"""

import pyspark.sql.functions as F
from pyspark.sql.types import StringType, IntegerType, DoubleType

from src.pipeline.silver.utils import (
    md5_surrogate_key, explode_month_columns, forward_fill,
    add_silver_metadata, write_to_duckdb, detect_month_columns
)
from src.utils.logger import logger


def transform_demand_forecast(duck_conn, spark, run_id: str, ts: str) -> int:
    logger.info("  slvr_dmnd_forecast")

    raw_df = spark.createDataFrame(
        duck_conn.execute("SELECT * FROM brnz_dmnd_forecast").df()
    )

    # Explode horizontal months → (month_key, demand_qty)
    exploded = explode_month_columns(raw_df, "demand_qty", "double")

    # Null demand → 0 (product not planned that month)
    exploded = exploded.withColumn(
        "demand_qty",
        F.coalesce(F.col("demand_qty"), F.lit(0.0))
    )

    # Clip to valid range
    exploded = exploded.withColumn(
        "demand_qty",
        F.greatest(F.lit(0.0), F.least(F.lit(5000.0), F.col("demand_qty")))
    )

    # Rename columns to match Silver schema
    exploded = (
        exploded
        .withColumnRenamed("site", "site_code")
        .withColumnRenamed("product_platform", "platform")
    )

    # Add data_type based on month_key
    exploded = exploded.withColumn(
        "data_type",
        F.when(F.col("month_key") <= 202606, "ACTUAL")
         .otherwise("FORECAST")
    )

    # Surrogate key
    exploded = md5_surrogate_key(
        exploded,
        ["site_code", "product_number", "month_key", "snapshot_id"],
        "dmnd_pk"
    )
    exploded = add_silver_metadata(exploded, run_id, ts)

    count = write_to_duckdb(
        exploded, "slvr_dmnd_forecast", duck_conn,
        partition_col="month_key",
        z_order_cols=["site_code", "product_number"]
    )
    logger.info(f"    {count:,} rows")
    return count


def transform_target_test_time(duck_conn, spark, run_id: str, ts: str) -> int:
    logger.info("  slvr_tgt_test_time")

    raw_df = spark.createDataFrame(
        duck_conn.execute("SELECT * FROM brnz_tgt_test_time").df()
    )

    exploded = explode_month_columns(raw_df, "target_test_time_sec", "double")

    exploded = (
        exploded
        .withColumnRenamed("site", "site_code")
    )

    # Test time null → is_valid = false (cannot compute capacity)
    exploded = exploded.withColumn(
        "is_valid",
        F.col("target_test_time_sec").isNotNull()
    ).withColumn(
        "invalid_reason",
        F.when(
            F.col("target_test_time_sec").isNull(),
            F.lit("NULL_TEST_TIME")
        ).otherwise(F.lit(None).cast(StringType()))
    )

    # Clip to valid range
    exploded = exploded.withColumn(
        "target_test_time_sec",
        F.greatest(F.lit(5.0), F.least(F.lit(3000.0),
                   F.col("target_test_time_sec")))
    )

    exploded = exploded.withColumn(
        "data_type",
        F.when(F.col("month_key") <= 202606, "ACTUAL").otherwise("FORECAST")
    )

    exploded = md5_surrogate_key(
        exploded,
        ["site_code", "product_number", "test_type", "month_key", "snapshot_id"],
        "ttt_pk"
    )
    exploded = add_silver_metadata(exploded, run_id, ts)

    count = write_to_duckdb(
        exploded, "slvr_tgt_test_time", duck_conn,
        partition_col="month_key",
        z_order_cols=["site_code", "product_number", "test_type"]
    )
    logger.info(f"    {count:,} rows")
    return count


def transform_target_yield(duck_conn, spark, run_id: str, ts: str) -> int:
    logger.info("  slvr_tgt_yield")

    raw_df = spark.createDataFrame(
        duck_conn.execute("SELECT * FROM brnz_tgt_yield").df()
    )

    exploded = explode_month_columns(raw_df, "target_yield", "double")

    exploded = (
        exploded
        .withColumnRenamed("site", "site_code")
    )

    # Forward fill nulls within (site, product, test_type) partition
    exploded = forward_fill(
        exploded,
        value_col="target_yield",
        partition_cols=["site_code", "product_number", "test_type",
                        "snapshot_id"],
        order_col="month_key"
    )

    # Clip yield to valid range
    exploded = exploded.withColumn(
        "target_yield",
        F.greatest(F.lit(0.50), F.least(F.lit(0.99),
                   F.col("target_yield")))
    )

    exploded = exploded.withColumn(
        "data_type",
        F.when(F.col("month_key") <= 202606, "ACTUAL").otherwise("FORECAST")
    )

    exploded = md5_surrogate_key(
        exploded,
        ["site_code", "product_number", "test_type", "month_key", "snapshot_id"],
        "tgt_yield_pk"
    )
    exploded = add_silver_metadata(exploded, run_id, ts)

    count = write_to_duckdb(
        exploded, "slvr_tgt_yield", duck_conn,
        partition_col="month_key",
        z_order_cols=["site_code", "product_number", "test_type"]
    )
    logger.info(f"    {count:,} rows")
    return count


def transform_site_equipment_inventory(
    duck_conn, spark, run_id: str, ts: str
) -> int:
    logger.info("  slvr_site_equip_inv")

    raw_df = spark.createDataFrame(
        duck_conn.execute("SELECT * FROM brnz_site_equip_inv").df()
    )

    # Non-month columns (static equipment attributes)
    static_cols = [
        "site", "platform", "family", "station", "cabinet",
        "test_type", "test_equipment_id", "test_equipment_desc",
        "equipment_type", "handling_time_sec", "qualification_time_sec",
        "cycle_time_sec", "utilization_rate", "yield_retest_1",
        "yield_retest_2_plus", "test_time_before_failure_hr",
        "retest_quote", "repair_tester", "is_npi_capable",
    ]

    # Explode monthly equipment quantity columns
    exploded = explode_month_columns(raw_df, "equip_qty_available", "integer")

    exploded = (
        exploded
        .withColumnRenamed("site", "site_code")
        .withColumn(
            "equip_qty_available",
            F.greatest(F.lit(0), F.col("equip_qty_available"))
        )
    )

    # Validate utilization range
    exploded = exploded.withColumn(
        "utilization_rate",
        F.greatest(F.lit(0.01), F.least(F.lit(1.0),
                   F.col("utilization_rate")))
    )

    exploded = md5_surrogate_key(
        exploded,
        ["site_code", "test_equipment_id", "month_key"],
        "equip_inv_pk"
    )
    exploded = add_silver_metadata(exploded, run_id, ts)

    count = write_to_duckdb(
        exploded, "slvr_site_equip_inv", duck_conn,
        partition_col="month_key",
        z_order_cols=["site_code", "test_type"]
    )
    logger.info(f"    {count:,} rows")
    return count


def transform_site_soft(duck_conn, spark, run_id: str, ts: str) -> int:
    """
    Site soft is stored in a very wide format:
    one row per site, columns like jan_2023_wd_normal, jan_2023_shifts_normal...

    Silver transform: explode to one row per (site, month_key) with
    all operational parameters as proper columns.
    """
    logger.info("  slvr_site_soft")

    raw_df = duck_conn.execute("SELECT * FROM brnz_site_soft").df()

    import re
    from src.utils.month_utils import month_label_to_key

    # Detect all unique month labels from column names
    # Pattern: mon_YYYY_metric_name
    month_pattern = re.compile(r"^([a-z]{3}_\d{4})_(.+)$")
    all_months = set()
    for col in raw_df.columns:
        m = month_pattern.match(col)
        if m:
            all_months.add(m.group(1))

    all_months_sorted = sorted(all_months, key=lambda x: month_label_to_key(x))
    metrics = [
        "wd_normal", "wd_extended", "wd_max",
        "shifts_normal", "shifts_mid", "shifts_max",
        "hrs_normal", "hrs_extended", "hrs_max",
        "allowance_pct", "productivity_pct",
    ]

    rows = []
    for _, row in raw_df.iterrows():
        site_code = row["site"]
        for month_label in all_months_sorted:
            month_key = month_label_to_key(month_label)
            out_row = {
                "site_code": site_code,
                "month_key": month_key,
            }
            for metric in metrics:
                col_name = f"{month_label}_{metric}"
                out_row[metric] = row.get(col_name)
            rows.append(out_row)

    import pandas as pd
    site_soft_pd = pd.DataFrame(rows)

    # Validate shift ordering
    site_soft_pd["is_valid"] = (
        (site_soft_pd["wd_normal"] <= site_soft_pd["wd_extended"]) &
        (site_soft_pd["wd_extended"] <= site_soft_pd["wd_max"]) &
        (site_soft_pd["shifts_normal"] <= site_soft_pd["shifts_max"])
    )
    site_soft_pd["invalid_reason"] = site_soft_pd.apply(
        lambda r: "SHIFT_PARAM_ORDER_VIOLATION"
        if not r["is_valid"] else None, axis=1
    )

    # MD5 surrogate key
    import hashlib
    site_soft_pd["site_soft_pk"] = site_soft_pd.apply(
        lambda r: hashlib.md5(
            f"{r['site_code']}|{r['month_key']}".encode()
        ).hexdigest(), axis=1
    )
    site_soft_pd["pipeline_run_id"] = run_id
    site_soft_pd["ingestion_ts"]    = ts

    duck_conn.execute("DROP TABLE IF EXISTS slvr_site_soft")
    duck_conn.register("_temp_soft", site_soft_pd)
    duck_conn.execute("""
        CREATE TABLE slvr_site_soft AS SELECT * FROM _temp_soft
    """)
    duck_conn.unregister("_temp_soft")
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_slvr_site_soft_month
        ON slvr_site_soft (month_key)
    """)

    count = duck_conn.execute(
        "SELECT COUNT(*) FROM slvr_site_soft"
    ).fetchone()[0]
    logger.info(f"    {count:,} rows")
    return count