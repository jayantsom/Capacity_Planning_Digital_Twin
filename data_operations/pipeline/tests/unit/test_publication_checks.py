"""Publication checks for business grains and Serving definitions."""

import duckdb
import pytest

from data_operations.pipeline.pipeline.database_staging import assert_unique_grain
from data_operations.pipeline.pipeline.gold.analytics import build_ml_feature_store
from data_operations.pipeline.pipeline.gold.serving_views import SERVING_VIEWS


def test_duplicate_business_grain_blocks_publication() -> None:
    """Fail instead of publishing a multiplied planning version join."""
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE actual_capacity (
                site_code VARCHAR,
                product_number VARCHAR,
                test_type VARCHAR,
                month_key INTEGER,
                planning_version_id VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO actual_capacity VALUES
                ('S1', 'P1', 'ICT', 202610, 'plan-2026-10-31'),
                ('S1', 'P1', 'ICT', 202610, 'plan-2026-10-31')
            """
        )
        with pytest.raises(ValueError, match="violates unique grain"):
            assert_unique_grain(
                connection,
                "actual_capacity",
                [
                    "site_code",
                    "product_number",
                    "test_type",
                    "month_key",
                    "planning_version_id",
                ],
            )


def test_every_serving_view_has_one_definition() -> None:
    """Keep the capacity summary definition unique and dead SQL absent."""
    assert list(SERVING_VIEWS).count("srv_vw_capacity_summary") == 1
    assert len(SERVING_VIEWS) == len(set(SERVING_VIEWS))


def test_ml_feature_store_collapses_qualified_resource_fanout() -> None:
    """Publish one feature row at the declared product/test/month grain."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE gold_gcm_base AS
        SELECT * FROM (
            VALUES
                ('S', 'P', 'Family', 'Platform', 'ICT', 202610,
                 'plan-2026-10-31', 80.0, 100.0, 0.95, 60.0, 'Region', 'SYSTEM-1',
                 DATE '2026-10-31', 'ACTUAL'),
                ('S', 'P', 'Family', 'Platform', 'ICT', 202610,
                 'plan-2026-10-31', 80.0, 100.0, 0.95, 60.0, 'Region', 'FIXTURE-1',
                 DATE '2026-10-31', 'ACTUAL')
        ) AS source(
            site_code, product_number, product_family, platform,
            test_type, month_key, planning_version_id, route_step_demand_qty,
            effective_demand_qty, target_yield,
            target_test_time_sec, region, equipment_id, plan_as_of_date, data_type
        )
        """
    )

    assert build_ml_feature_store(connection) == 1
    row = connection.execute(
        """
        SELECT demand_qty, qualified_resource_count
        FROM gold_ml_feature_store
        """
    ).fetchone()
    connection.close()

    assert row == (80.0, 2)
