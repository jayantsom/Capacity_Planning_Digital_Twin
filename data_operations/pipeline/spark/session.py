"""
PySpark session factory.
Single source of truth for Spark configuration.
All Silver and Gold pipeline modules import get_spark_session() from here.
"""

from pyspark.sql import SparkSession

from capacity_twin_core.logging import logger
from capacity_twin_core.runtime.database_paths import (
    get_runtime_home,
    load_app_config,
)


def get_spark_session(app_name: str | None = None) -> SparkSession:
    """
    Create or retrieve existing Spark session.
    Configured for local mode with DuckDB-compatible settings.
    """
    spark_runtime = get_runtime_home() / "spark"
    spark_config = load_app_config("data_operations.pipeline")["spark"]
    resolved_app_name = app_name or spark_config["app_name"]
    warehouse = spark_runtime / "warehouse"
    local_dir = spark_runtime / "local"
    warehouse.mkdir(parents=True, exist_ok=True)
    local_dir.mkdir(parents=True, exist_ok=True)
    spark = (
        SparkSession.builder
        .appName(resolved_app_name)
        .master(spark_config["master"])
        .config("spark.sql.shuffle.partitions", str(spark_config["shuffle_partitions"]))
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
        .config("spark.driver.memory", spark_config["driver_memory"])
        .config("spark.sql.execution.arrow.pyspark.enabled", "true")
        .config(
            "spark.sql.autoBroadcastJoinThreshold",
            str(int(spark_config["broadcast_threshold_mb"]) * 1024 * 1024),
        )
        .config("spark.ui.showConsoleProgress", "false")
        .config("spark.sql.warehouse.dir", str(warehouse))
        .config("spark.local.dir", str(local_dir))
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    logger.info(f"Spark session ready: {resolved_app_name} "
                f"[{spark.version}]")
    return spark