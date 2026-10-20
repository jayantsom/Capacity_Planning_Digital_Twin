"""
Silver transforms: planning tables.
Explodes horizontal month columns → row-per-month format.
brnz_demand_requirement → slvr_demand_requirement
brnz_tgt_test_time   → slvr_tgt_test_time
brnz_tgt_yield       → slvr_tgt_yield
brnz_site_equip_inv  → slvr_site_equip_inv
brnz_site_soft       → slvr_site_soft
"""

import pyspark.sql.functions as F

from capacity_twin_core.logging import logger
from data_operations.pipeline.pipeline.silver.utils import (
    add_silver_metadata,
    add_validation_issue,
    explode_month_columns,
    forward_fill,
    md5_surrogate_key,
    write_to_duckdb,
)


def transform_demand_requirements(duck_conn, run_id: str, ts: str) -> int:
    """Clean the explicit independent and BOM-dependent demand contract."""
    logger.info("  slvr_demand_requirement")
    duck_conn.execute("DROP TABLE IF EXISTS slvr_demand_requirement")
    duck_conn.execute(
        """
        CREATE TABLE slvr_demand_requirement AS
        SELECT
            demand_id,
            CAST(snapshot_id AS VARCHAR) AS snapshot_id,
            CAST(snapshot_date AS DATE) AS snapshot_date,
            CAST(month_key AS INTEGER) AS month_key,
            CAST(site AS VARCHAR) AS site_code,
            CAST(product_number AS VARCHAR) AS product_number,
            CAST(demand_class AS VARCHAR) AS demand_class,
            CAST(parent_product_number AS VARCHAR) AS parent_product_number,
            CASE
                WHEN UPPER(CAST(knowledge_type AS VARCHAR)) IN ('ACTUAL', 'FORECAST')
                    THEN UPPER(CAST(knowledge_type AS VARCHAR))
                WHEN CAST(month_key AS INTEGER) <=
                    EXTRACT(YEAR FROM CAST(snapshot_date AS DATE)) * 100
                    + EXTRACT(MONTH FROM CAST(snapshot_date AS DATE))
                    THEN 'ACTUAL'
                ELSE 'FORECAST'
            END AS data_type,
            CAST(GREATEST(COALESCE(quantity, 0), 0) AS DOUBLE) AS demand_qty,
            CAST(GREATEST(COALESCE(independent_quantity, 0), 0) AS DOUBLE)
                AS independent_demand_qty,
            CAST(GREATEST(COALESCE(dependent_quantity, 0), 0) AS DOUBLE)
                AS dependent_demand_qty,
            CAST(GREATEST(COALESCE(total_requirement, 0), 0) AS DOUBLE)
                AS total_requirement_qty,
            CAST(data_provenance AS VARCHAR) AS data_provenance,
            is_valid,
            CAST(invalid_reason AS VARCHAR) AS invalid_reason,
            bronze_id,
            ? AS pipeline_run_id,
            ? AS silver_created_at
        FROM brnz_demand_requirement
        """
        ,
        [run_id, ts],
    )
    duck_conn.execute(
        """
        CREATE INDEX idx_slvr_demand_requirement_grain
        ON slvr_demand_requirement (
            site_code, product_number, month_key, snapshot_id, demand_class
        )
        """
    )
    count = duck_conn.execute(
        "SELECT COUNT(*) FROM slvr_demand_requirement"
    ).fetchone()[0]
    logger.info(f"    {count:,} rows")
    return count


def transform_target_test_time(duck_conn, spark, run_id: str, ts: str) -> int:
    logger.info("  slvr_tgt_test_time")

    raw_df = spark.createDataFrame(
        duck_conn.execute("SELECT * FROM brnz_tgt_test_time").df()
    )

    exploded = explode_month_columns(raw_df, "target_test_time_sec", "double")
    exploded = exploded.withColumn(
        "source_value_was_null", F.col("target_test_time_sec").isNull()
    )

    exploded = (
        exploded
        .withColumnRenamed("site", "site_code")
    )

    # Test time null → is_valid = false (cannot compute capacity)
    exploded = add_validation_issue(
        exploded,
        F.col("target_test_time_sec").isNull(),
        "NULL_TEST_TIME",
    )

    # Clip to valid range
    exploded = exploded.withColumn(
        "target_test_time_sec",
        F.greatest(F.lit(5.0), F.least(F.lit(3000.0),
                   F.col("target_test_time_sec")))
    )

    exploded = exploded.withColumn(
        "data_type",
        F.when(
            F.col("month_key")
            <= (
                F.year(F.to_date("snapshot_date")) * 100
                + F.month(F.to_date("snapshot_date"))
            ),
            "ACTUAL",
        ).otherwise("FORECAST")
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
    exploded = exploded.withColumn(
        "source_value_was_null", F.col("target_yield").isNull()
    )
    exploded = add_validation_issue(
        exploded, F.col("source_value_was_null"), "NULL_MONTH_VALUE"
    )

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
        F.when(
            F.col("month_key")
            <= (
                F.year(F.to_date("snapshot_date")) * 100
                + F.month(F.to_date("snapshot_date"))
            ),
            "ACTUAL",
        ).otherwise("FORECAST")
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

    # Explode monthly equipment quantity columns
    exploded = explode_month_columns(raw_df, "equip_qty_available", "integer")
    exploded = exploded.withColumn(
        "source_value_was_null", F.col("equip_qty_available").isNull()
    )
    exploded = add_validation_issue(
        exploded, F.col("source_value_was_null"), "NULL_MONTH_VALUE"
    )

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

    from capacity_twin_core.dates.months import month_label_to_key

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