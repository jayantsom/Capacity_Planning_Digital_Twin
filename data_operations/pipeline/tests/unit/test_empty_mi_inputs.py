"""Empty MI inputs still publish queryable Silver schemas."""

import duckdb

from data_operations.pipeline.pipeline.silver.transforms_mi import transform_mi_execution


def test_empty_execution_creates_schema_and_indexes() -> None:
    """An empty but valid source must not fail a pipeline run."""
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE brnz_mi_execution (
                factory_code VARCHAR, site_code VARCHAR, product_number VARCHAR,
                product_type VARCHAR, test_category_id VARCHAR, test_type VARCHAR,
                execution_date DATE, month_key INTEGER, passed_qty DOUBLE,
                failed_qty DOUBLE, total_qty DOUBLE, yield_avg DOUBLE,
                final_test_yield_avg DOUBLE, test_duration_avg_sec DOUBLE,
                handling_time_avg_sec DOUBLE, setup_time_avg_sec DOUBLE,
                load_unload_time_avg_sec DOUBLE, idle_time_avg_sec DOUBLE,
                retest_count_avg DOUBLE, equipment_downtime_avg_sec DOUBLE,
                actual_throughput_uph DOUBLE, is_valid BOOLEAN
            )
            """
        )

        count = transform_mi_execution(
            connection, spark=None, run_id="run", ts="now"
        )

        assert count == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM slvr_mi_execution"
        ).fetchone()[0] == 0
        index_names = {
            row[0]
            for row in connection.execute(
                """
                SELECT index_name
                FROM duckdb_indexes()
                WHERE table_name = 'slvr_mi_execution'
                """
            ).fetchall()
        }
        assert "idx_slvr_mi_exec_month" in index_names
