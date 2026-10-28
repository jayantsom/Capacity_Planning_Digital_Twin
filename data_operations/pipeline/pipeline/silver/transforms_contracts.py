"""Publish conformed canonical keys and governed manufacturing resource contracts."""

from __future__ import annotations

import duckdb

from data_operations.pipeline.pipeline.silver.equipment_cost_reference import (
    build_equipment_cost_reference,
)


def _replace(connection: duckdb.DuckDBPyConnection, table: str, sql: str) -> int:
    temporary = f"_{table}_conformed"
    connection.execute(f'DROP TABLE IF EXISTS "{temporary}"')
    connection.execute(f'CREATE TABLE "{temporary}" AS {sql}')
    connection.execute(f'DROP TABLE "{table}"')
    connection.execute(f'ALTER TABLE "{temporary}" RENAME TO "{table}"')
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _require_complete_mapping(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    canonical_columns: list[str],
) -> None:
    predicate = " OR ".join(f'"{column}" IS NULL' for column in canonical_columns)
    missing = int(
        connection.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE {predicate}'
        ).fetchone()[0]
    )
    if missing:
        raise ValueError(f"{table} has {missing} rows with unresolved canonical keys")


def build_conformed_contracts(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    created_at: str,
    *,
    source_run_id: str,
    source_bundle_checksum: str,
) -> dict[str, int]:
    """Resolve source-local codes using the pinned Reference and Mapping catalogs."""
    counts: dict[str, int] = {}

    simple_tables = {
        "slvr_manufacturer_master": """
            SELECT
                * EXCLUDE (pipeline_run_id),
                CAST(manufacturer AS VARCHAR) AS canonical_manufacturer_id,
                ? AS pipeline_run_id,
                ? AS silver_created_at
            FROM brnz_manufacturer_master
        """,
        "slvr_product_bom": """
            SELECT
                b.* EXCLUDE (pipeline_run_id),
                CAST(parent.product_number AS VARCHAR) AS canonical_parent_product_id,
                CAST(child.product_number AS VARCHAR) AS canonical_child_product_id,
                CAST(b.quantity_per_parent AS DOUBLE) AS quantity_per_parent_ea,
                ? AS pipeline_run_id,
                ? AS silver_created_at
            FROM brnz_product_bom b
            LEFT JOIN reference.canonical.product parent
              ON b.parent_product_number = parent.product_number
            LEFT JOIN reference.canonical.product child
              ON b.child_product_number = child.product_number
        """,
        "slvr_product_route": """
            SELECT
                r.* EXCLUDE (pipeline_run_id),
                CAST(p.product_number AS VARCHAR) AS canonical_product_id,
                CAST(r.route_id AS VARCHAR) AS canonical_route_id,
                ? AS pipeline_run_id,
                ? AS silver_created_at
            FROM brnz_product_route r
            LEFT JOIN reference.canonical.product p
              ON r.product_number = p.product_number
        """,
        "slvr_route_step": """
            SELECT
                s.* EXCLUDE (pipeline_run_id),
                CAST(s.route_id AS VARCHAR) AS canonical_route_id,
                CAST(t.test_type AS VARCHAR) AS canonical_test_type_id,
                CAST(s.route_step_id AS VARCHAR) AS canonical_route_step_id,
                ? AS pipeline_run_id,
                ? AS silver_created_at
            FROM brnz_route_step s
            LEFT JOIN reference.canonical.test_type t
              ON s.test_type = t.test_type
        """,
        "slvr_site_product_source": """
            SELECT
                s.* EXCLUDE (pipeline_run_id),
                CAST(site.site_code AS VARCHAR) AS canonical_site_id,
                CAST(product.product_number AS VARCHAR) AS canonical_product_id,
                CAST(s.allocation_ratio AS DOUBLE) AS allocation_ratio_pct,
                ? AS pipeline_run_id,
                ? AS silver_created_at
            FROM brnz_site_product_source s
            LEFT JOIN reference.canonical.site site ON s.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON s.product_number = product.product_number
        """,
    }
    for table, sql in simple_tables.items():
        connection.execute(f'DROP TABLE IF EXISTS "{table}"')
        connection.execute(f'CREATE TABLE "{table}" AS {sql}', [run_id, created_at])
        counts[table] = int(
            connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        )

    required = {
        "slvr_product_bom": [
            "canonical_parent_product_id",
            "canonical_child_product_id",
        ],
        "slvr_product_route": ["canonical_product_id", "canonical_route_id"],
        "slvr_route_step": ["canonical_route_id", "canonical_test_type_id"],
        "slvr_site_product_source": ["canonical_site_id", "canonical_product_id"],
    }
    for table, columns in required.items():
        _require_complete_mapping(connection, table, columns)

    counts["slvr_demand_requirement"] = _replace(
        connection,
        "slvr_demand_requirement",
        """
        SELECT d.*,
               CAST(site.site_code AS VARCHAR) AS canonical_site_id,
               CAST(product.product_number AS VARCHAR) AS canonical_product_id
        FROM slvr_demand_requirement d
        LEFT JOIN reference.canonical.site site ON d.site_code = site.site_code
        LEFT JOIN reference.canonical.product product
          ON d.product_number = product.product_number
        """,
    )
    counts["slvr_tgt_test_time"] = _replace(
        connection,
        "slvr_tgt_test_time",
        """
        SELECT t.*,
               CAST(site.site_code AS VARCHAR) AS canonical_site_id,
               CAST(product.product_number AS VARCHAR) AS canonical_product_id,
               CAST(test.test_type AS VARCHAR) AS canonical_test_type_id
        FROM slvr_tgt_test_time t
        LEFT JOIN reference.canonical.site site ON t.site_code = site.site_code
        LEFT JOIN reference.canonical.product product
          ON t.product_number = product.product_number
        LEFT JOIN reference.canonical.test_type test ON t.test_type = test.test_type
        """,
    )
    counts["slvr_tgt_yield"] = _replace(
        connection,
        "slvr_tgt_yield",
        """
        SELECT y.*,
               CAST(site.site_code AS VARCHAR) AS canonical_site_id,
               CAST(product.product_number AS VARCHAR) AS canonical_product_id,
               CAST(test.test_type AS VARCHAR) AS canonical_test_type_id
        FROM slvr_tgt_yield y
        LEFT JOIN reference.canonical.site site ON y.site_code = site.site_code
        LEFT JOIN reference.canonical.product product
          ON y.product_number = product.product_number
        LEFT JOIN reference.canonical.test_type test ON y.test_type = test.test_type
        """,
    )
    counts["slvr_site_equip_inv"] = _replace(
        connection,
        "slvr_site_equip_inv",
        """
        SELECT i.*,
               CAST(site.site_code AS VARCHAR) AS canonical_site_id,
               CAST(machine.equipment_id AS VARCHAR) AS canonical_machine_id,
               CAST(test.test_type AS VARCHAR) AS canonical_test_type_id
        FROM slvr_site_equip_inv i
        LEFT JOIN reference.canonical.site site ON i.site_code = site.site_code
        LEFT JOIN reference.canonical.machine machine
          ON i.test_equipment_id = machine.equipment_id
        LEFT JOIN reference.canonical.test_type test ON i.test_type = test.test_type
        """,
    )
    counts["slvr_site_soft"] = _replace(
        connection,
        "slvr_site_soft",
        """
        SELECT s.*, CAST(site.site_code AS VARCHAR) AS canonical_site_id
        FROM slvr_site_soft s
        LEFT JOIN reference.canonical.site site ON s.site_code = site.site_code
        """,
    )
    for table in (
        "slvr_machine_execution",
        "slvr_machine_test_param",
        "slvr_machine_logs",
    ):
        counts[table] = _replace(
            connection,
            table,
            f"""
            SELECT fact.*,
                   CAST(site.site_code AS VARCHAR) AS canonical_site_id,
                   CAST(product.product_number AS VARCHAR) AS canonical_product_id,
                   CAST(test.test_type AS VARCHAR) AS canonical_test_type_id
            FROM {table} fact
            LEFT JOIN reference.canonical.site site
              ON fact.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON fact.product_number = product.product_number
            LEFT JOIN reference.canonical.test_type test
              ON fact.test_type = test.test_type
            """,
        )

    for table, columns in {
        "slvr_demand_requirement": ["canonical_site_id", "canonical_product_id"],
        "slvr_tgt_test_time": [
            "canonical_site_id",
            "canonical_product_id",
            "canonical_test_type_id",
        ],
        "slvr_tgt_yield": [
            "canonical_site_id",
            "canonical_product_id",
            "canonical_test_type_id",
        ],
        "slvr_site_equip_inv": [
            "canonical_site_id",
            "canonical_machine_id",
            "canonical_test_type_id",
        ],
        "slvr_site_soft": ["canonical_site_id"],
        "slvr_machine_execution": [
            "canonical_site_id",
            "canonical_product_id",
            "canonical_test_type_id",
        ],
        "slvr_machine_test_param": [
            "canonical_site_id",
            "canonical_product_id",
            "canonical_test_type_id",
        ],
        "slvr_machine_logs": [
            "canonical_site_id",
            "canonical_product_id",
            "canonical_test_type_id",
        ],
    }.items():
        _require_complete_mapping(connection, table, columns)

    connection.execute("DROP TABLE IF EXISTS slvr_resource_contract")
    connection.execute(
        """
        CREATE TABLE slvr_resource_contract AS
        WITH compatibility AS (
            SELECT * EXCLUDE (compatibility_rank)
            FROM (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY tester_resource_id
                        ORDER BY fixture_resource_id, compatibility_id
                    ) AS compatibility_rank
                FROM mapping.resource.tester_fixture_compatibility
                WHERE is_active = 1
            )
            WHERE compatibility_rank = 1
        )
        SELECT
            q.qualification_id,
            q.site_code,
            q.product_number,
            q.test_type,
            q.resource_id,
            q.pool_id,
            q.capacity_behavior AS resource_behavior,
            q.is_primary,
            q.effective_start_date,
            q.effective_end_date,
            r.resource_kind,
            r.resource_family,
            r.is_passive,
            pool.pool_behavior,
            compatibility.fixture_resource_id AS paired_fixture_resource_id,
            compatibility.handler_resource_id,
            compatibility.fixture_slots_required,
            multi.tester_channels,
            multi.enabled_licensed_ports,
            multi.tester_fixture_slots,
            multi.fixture_cavities,
            multi.handler_sockets,
            multi.fixtures_required_per_system,
            multi.execution_mode,
            multi.batch_cycle_time_sec,
            multi.changeover_time_sec,
            multi.parallel_efficiency,
            multi.effective_parallel_duts,
            CAST(site.site_code AS VARCHAR) AS canonical_site_id,
            CAST(product.product_number AS VARCHAR) AS canonical_product_id,
            CAST(test.test_type AS VARCHAR) AS canonical_test_type_id,
            CAST(machine.equipment_id AS VARCHAR) AS canonical_resource_id,
            ? AS pipeline_run_id,
            ? AS silver_created_at
        FROM mapping.resource.product_resource_qualification q
        JOIN mapping.resource.resource_master r ON q.resource_id = r.resource_id
        LEFT JOIN mapping.resource.resource_pool pool
          ON q.pool_id = pool.pool_id AND q.resource_id = pool.resource_id
        LEFT JOIN compatibility
          ON q.resource_id = compatibility.tester_resource_id
        LEFT JOIN mapping.resource.multi_dut_configuration multi
          ON q.resource_id = multi.resource_id
        LEFT JOIN reference.canonical.site site ON q.site_code = site.site_code
        LEFT JOIN reference.canonical.product product
          ON q.product_number = product.product_number
        LEFT JOIN reference.canonical.test_type test ON q.test_type = test.test_type
        LEFT JOIN reference.canonical.machine machine
          ON q.resource_id = machine.equipment_id
        """,
        [run_id, created_at],
    )
    _require_complete_mapping(
        connection,
        "slvr_resource_contract",
        [
            "canonical_site_id",
            "canonical_product_id",
            "canonical_test_type_id",
            "canonical_resource_id",
        ],
    )
    counts["slvr_resource_contract"] = int(
        connection.execute("SELECT COUNT(*) FROM slvr_resource_contract").fetchone()[0]
    )
    counts["slvr_equipment_cost_reference"] = build_equipment_cost_reference(
        connection,
        created_at,
    )

    connection.execute("DROP TABLE IF EXISTS slvr_source_publication")
    connection.execute(
        """
        CREATE TABLE slvr_source_publication AS
        SELECT ? AS source_run_id,
               ? AS source_bundle_checksum,
               ? AS pipeline_run_id,
               ? AS silver_created_at
        """,
        [source_run_id, source_bundle_checksum, run_id, created_at],
    )
    counts["slvr_source_publication"] = 1
    return counts
