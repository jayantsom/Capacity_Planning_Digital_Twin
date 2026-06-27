"""
PySpark session factory.
Single source of truth for Spark configuration.
All Silver and Gold pipeline modules import get_spark_session() from here.
"""

from pyspark.sql import SparkSession
from src.utils.logger import logger


def get_spark_session(app_name: str = "capacity_planning_digital_twin") -> SparkSession:
    """
    Create or retrieve existing Spark session.
    Configured for local mode with DuckDB-compatible settings.
    """
    spark = (
        SparkSession.builder
        .appName(app_name)
        .master("local[*]")
        .config("spark.sql.shuffle.partitions", "12")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
        .config("spark.driver.memory", "4g")
        .config("spark.sql.execution.arrow.pyspark.enabled", "true")
        .config("spark.sql.autoBroadcastJoinThreshold", "52428800")  # 50MB
        .config("spark.ui.showConsoleProgress", "false")
        .config("spark.sql.warehouse.dir", "spark-warehouse")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    logger.info(f"Spark session ready: {app_name} "
                f"[{spark.version}]")
    return spark