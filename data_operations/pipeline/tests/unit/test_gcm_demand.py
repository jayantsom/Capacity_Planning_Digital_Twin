"""Regression tests for explicit parent and child demand in Gold."""

import duckdb

from data_operations.pipeline.pipeline.gold.gcm_base import build_gcm_base
from data_operations.pipeline.pipeline.silver.transforms_planning import (
    transform_demand_requirements,
)


def test_silver_derives_missing_bom_knowledge_type_from_snapshot() -> None:
    """Repair missing Raw demand type before Gold combines demand classes."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE brnz_demand_requirement AS
        SELECT
            'demand-1' AS demand_id,
            'snap' AS snapshot_id,
            '2026-10-31' AS snapshot_date,
            202609 AS month_key,
            'S' AS site,
            'CHILD' AS product_number,
            'BOM_DEPENDENT' AS demand_class,
            'PARENT' AS parent_product_number,
            NULL::VARCHAR AS knowledge_type,
            20 AS quantity,
            0 AS independent_quantity,
            20 AS dependent_quantity,
            20 AS total_requirement,
            'BOM_EXPLOSION' AS data_provenance,
            true AS is_valid,
            NULL::VARCHAR AS invalid_reason,
            'bronze-1' AS bronze_id
        """
    )

    transform_demand_requirements(connection, "run", "now")
    data_type = connection.execute(
        "SELECT data_type FROM slvr_demand_requirement"
    ).fetchone()[0]
    connection.close()

    assert data_type == "ACTUAL"


def test_gcm_sums_independent_and_dependent_child_demand_once() -> None:
    """Test a child route once for its reconciled total requirement."""
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE slvr_demand_requirement AS
        SELECT * FROM (
            VALUES
                ('S', 'CHILD', 202611, 'snap', DATE '2026-10-31', 'FORECAST',
                 10.0, 0.0, 10.0, 'DIRECT_CUSTOMER', NULL, true),
                ('S', 'CHILD', 202611, 'snap', DATE '2026-10-31', 'FORECAST',
                 5.0, 0.0, 5.0, 'SPARE', NULL, true),
                ('S', 'CHILD', 202611, 'snap', DATE '2026-10-31', 'FORECAST',
                 0.0, 20.0, 20.0, 'BOM_DEPENDENT', 'PARENT-A', true),
                ('S', 'CHILD', 202611, 'snap', DATE '2026-10-31', 'FORECAST',
                 0.0, 30.0, 30.0, 'BOM_DEPENDENT', 'PARENT-B', true)
        ) AS source(
            site_code, product_number, month_key, snapshot_id, snapshot_date,
            data_type, independent_demand_qty, dependent_demand_qty,
            total_requirement_qty, demand_class, parent_product_number, is_valid
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE slvr_prod_master AS
        SELECT 'CHILD' AS product_number, 'Child board' AS product_description,
               'Board' AS product_family, 'Platform' AS platform,
               'ACTIVE' AS product_status, 'PCBA' AS product_type,
               'Owner' AS product_poc, 0 AS is_parent, 0 AS has_children,
               true AS is_valid
        """
    )
    connection.execute(
        """
        CREATE TABLE slvr_tgt_test_time AS
        SELECT 'S' AS site_code, 'CHILD' AS product_number, 202611 AS month_key,
               'snap' AS snapshot_id, 'ICT' AS test_type, 'CAT' AS test_category_id,
               'Owner' AS responsible_person, 30.0 AS target_test_time_sec,
               true AS is_valid
        """
    )
    connection.execute(
        """
        CREATE TABLE slvr_tgt_yield AS
        SELECT 'S' AS site_code, 'CHILD' AS product_number, 202611 AS month_key,
               'snap' AS snapshot_id, 'ICT' AS test_type, 0.95 AS target_yield,
               false AS is_forward_filled, true AS is_valid
        """
    )
    connection.execute(
        """
        CREATE TABLE slvr_site_equip_inv AS
        SELECT 'S' AS site_code, 202611 AS month_key, 'ICT' AS test_type,
               'ICT-1' AS test_equipment_id, 'SYSTEM' AS equipment_type,
               1.0 AS handling_time_sec, 0.0 AS qualification_time_sec,
               30.0 AS cycle_time_sec, 0.85 AS utilization_rate,
               0.9 AS yield_retest_1, 0.95 AS yield_retest_2_plus,
               0.75 AS retest_quote, 1.0 AS equip_qty_available, true AS is_valid
        """
    )
    connection.execute(
        """
        CREATE TABLE slvr_site_soft AS
        SELECT 'S' AS site_code, 202611 AS month_key, 20.0 AS wd_normal,
               2.0 AS shifts_normal, 8.0 AS hrs_normal, 22.0 AS wd_max,
               3.0 AS shifts_max, 8.0 AS hrs_max, 0.1 AS allowance_pct,
               0.85 AS productivity_pct, true AS is_valid
        """
    )
    connection.execute(
        """
        CREATE TABLE slvr_ref_site AS
        SELECT 'S' AS site_code, 'F' AS factory_code, 'Region' AS region,
               'Supplier' AS supplier_name, 'Country' AS country, true AS is_valid
        """
    )
    connection.execute(
        """
        CREATE TABLE slvr_ref_test_type AS
        SELECT 'ICT' AS test_type, 'In-circuit test' AS test_category_name,
               true AS is_valid
        """
    )

    build_gcm_base(connection)
    row = connection.execute(
        """
        SELECT effective_demand_qty, independent_demand_qty,
               dependent_demand_qty, demand_classes, parent_product_numbers
        FROM gold_gcm_base
        """
    ).fetchone()
    connection.close()

    assert row[:3] == (65.0, 15.0, 50.0)
    assert set(row[3].split(",")) == {"BOM_DEPENDENT", "DIRECT_CUSTOMER", "SPARE"}
    assert set(row[4].split(",")) == {"PARENT-A", "PARENT-B"}
