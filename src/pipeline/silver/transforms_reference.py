"""
Silver transforms: reference and master tables.
brnz_ref_* → slvr_ref_*
brnz_prod_master → slvr_prod_master + slvr_prod_hierarchy
"""

import uuid
from datetime import datetime

import pyspark.sql.functions as F
from pyspark.sql.types import StringType

from src.utils.spark_utils import get_spark_session
from src.utils.db_utils import get_duckdb_connection
from src.pipeline.silver.utils import (
    md5_surrogate_key, add_silver_metadata, write_to_duckdb
)
from src.utils.logger import logger


def transform_reference_tables(duck_conn, spark, run_id: str, ts: str) -> dict:
    """Transform all reference tables Bronze → Silver."""
    counts = {}

    # ── slvr_ref_site ──────────────────────────────────────────────────────
    logger.info("  slvr_ref_site")
    site_df = spark.createDataFrame(
        duck_conn.execute("SELECT * FROM brnz_ref_site").df()
    )
    site_df = md5_surrogate_key(site_df, ["site_code"], "site_pk")
    site_df = add_silver_metadata(site_df, run_id, ts)
    site_df = site_df.dropDuplicates(["site_code"])
    counts["slvr_ref_site"] = write_to_duckdb(
        site_df, "slvr_ref_site", duck_conn
    )
    logger.info(f"    {counts['slvr_ref_site']:,} rows")

    # ── slvr_ref_test_type ─────────────────────────────────────────────────
    logger.info("  slvr_ref_test_type")
    tt_df = spark.createDataFrame(
        duck_conn.execute("SELECT * FROM brnz_ref_test_type").df()
    )
    tt_df = md5_surrogate_key(tt_df, ["test_type"], "test_type_pk")
    tt_df = add_silver_metadata(tt_df, run_id, ts)
    tt_df = tt_df.dropDuplicates(["test_type"])
    counts["slvr_ref_test_type"] = write_to_duckdb(
        tt_df, "slvr_ref_test_type", duck_conn
    )
    logger.info(f"    {counts['slvr_ref_test_type']:,} rows")

    # ── slvr_ref_equipment ─────────────────────────────────────────────────
    logger.info("  slvr_ref_equipment")
    eq_df = spark.createDataFrame(
        duck_conn.execute("SELECT * FROM brnz_ref_equipment").df()
    )
    eq_df = md5_surrogate_key(eq_df, ["equipment_id"], "equipment_pk")
    eq_df = add_silver_metadata(eq_df, run_id, ts)
    eq_df = eq_df.dropDuplicates(["equipment_id"])
    counts["slvr_ref_equipment"] = write_to_duckdb(
        eq_df, "slvr_ref_equipment", duck_conn
    )
    logger.info(f"    {counts['slvr_ref_equipment']:,} rows")

    return counts


def transform_product_tables(duck_conn, spark, run_id: str, ts: str) -> dict:
    """
    Transform product master Bronze → Silver.
    Produces: slvr_prod_master + slvr_prod_hierarchy
    """
    counts = {}

    raw_df = spark.createDataFrame(
        duck_conn.execute("SELECT * FROM brnz_prod_master").df()
    )

    # ── slvr_prod_master ───────────────────────────────────────────────────
    logger.info("  slvr_prod_master")
    master_cols = [
        "product_number", "product_description", "product_type",
        "product_family", "platform", "category", "product_poc",
        "product_status", "is_parent", "has_children",
    ]
    master_df = raw_df.select(*master_cols)
    master_df = md5_surrogate_key(master_df, ["product_number"], "prod_pk")
    master_df = add_silver_metadata(master_df, run_id, ts)
    master_df = master_df.dropDuplicates(["product_number"])
    counts["slvr_prod_master"] = write_to_duckdb(
        master_df, "slvr_prod_master", duck_conn
    )
    logger.info(f"    {counts['slvr_prod_master']:,} rows")

    # ── slvr_prod_hierarchy ────────────────────────────────────────────────
    logger.info("  slvr_prod_hierarchy")

    # Unpivot child columns: (child_product_1, quantity_child_1), etc.
    child_dfs = []
    for i in range(1, 4):
        child_col = f"child_product_{i}"
        qty_col   = f"quantity_child_{i}"

        if child_col not in raw_df.columns:
            continue

        child_df = (
            raw_df
            .filter(F.col(child_col).isNotNull())
            .select(
                F.col("product_number").alias("parent_product_number"),
                F.col(child_col).alias("child_product_number"),
                F.lit(i).alias("child_sequence"),
                F.col(qty_col).cast("double").alias("child_quantity"),
            )
        )
        child_dfs.append(child_df)

    if child_dfs:
        from functools import reduce
        hierarchy_df = reduce(lambda a, b: a.union(b), child_dfs)

        hierarchy_df = md5_surrogate_key(
            hierarchy_df,
            ["parent_product_number", "child_product_number"],
            "hier_pk"
        )
        hierarchy_df = add_silver_metadata(hierarchy_df, run_id, ts)
        counts["slvr_prod_hierarchy"] = write_to_duckdb(
            hierarchy_df, "slvr_prod_hierarchy", duck_conn
        )
        logger.info(f"    {counts['slvr_prod_hierarchy']:,} rows")

    return counts