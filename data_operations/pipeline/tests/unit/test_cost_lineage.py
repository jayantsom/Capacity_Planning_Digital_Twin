"""Contracts for the retained equipment-cost lineage."""

import duckdb

from data_operations.pipeline.pipeline.gold.equipment_cost_reference import (
    build_equipment_cost_reference,
)
from data_operations.pipeline.pipeline.gold.serving_views import SERVING_VIEWS


def test_equipment_cost_reference_reaches_gold_and_serving() -> None:
    with duckdb.connect() as connection:
        connection.execute(
            """
            CREATE TABLE slvr_equipment_cost_reference AS
            SELECT
                'COST-1' AS equipment_cost_reference_id,
                'EQ-1' AS equipment_id,
                'EQ-1' AS canonical_equipment_id,
                DATE '2026-01-01' AS effective_start_date,
                DATE '2099-12-31' AS effective_end_date,
                100000.0 AS purchase_cost_usd,
                5000.0 AS annual_maintenance_cost_usd,
                7500.0 AS installation_cost_usd,
                90 AS lead_time_days,
                'USD' AS currency_code,
                'ACTIVE' AS cost_status,
                true AS is_valid
            """
        )
        connection.execute(
            """
            CREATE TABLE slvr_ref_equipment AS
            SELECT
                'EQ-1' AS equipment_id,
                'Tester' AS equipment_name,
                'Vendor' AS manufacturer
            """
        )

        assert build_equipment_cost_reference(connection) == 1
        connection.execute(
            "CREATE TABLE srv_equipment_cost_reference AS "
            + SERVING_VIEWS["srv_equipment_cost_reference"]
        )

        assert connection.execute(
            """
            SELECT equipment_name, purchase_cost_usd
            FROM srv_equipment_cost_reference
            """
        ).fetchone() == ("Tester", 100000.0)
