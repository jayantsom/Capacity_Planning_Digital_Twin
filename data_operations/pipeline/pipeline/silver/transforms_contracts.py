"""Publish conformed canonical keys and governed manufacturing resource contracts."""

from __future__ import annotations

import duckdb


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


def build_planning_foundation(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    created_at: str,
) -> dict[str, int]:
    """Conform Phase 6 source facts without changing their source-level meaning."""
    statements = {
        "slvr_customer_order": """
            SELECT b.*, site.site_code AS canonical_site_id,
                   product.product_number AS canonical_product_id
            FROM brnz_customer_order b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON b.product_number = product.product_number
        """,
        "slvr_backlog_position": """
            SELECT b.*, site.site_code AS canonical_site_id,
                   product.product_number AS canonical_product_id
            FROM brnz_backlog_position b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON b.product_number = product.product_number
        """,
        "slvr_constrained_production_plan": """
            SELECT b.*, site.site_code AS canonical_site_id,
                   product.product_number AS canonical_product_id
            FROM brnz_constrained_production_plan b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON b.product_number = product.product_number
        """,
        "slvr_shared_resource_allocation": """
            SELECT b.*, site.site_code AS canonical_site_id,
                   product.product_number AS canonical_product_id,
                   machine.equipment_id AS canonical_resource_id
            FROM brnz_shared_resource_allocation b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON b.product_number = product.product_number
            LEFT JOIN reference.canonical.machine machine
              ON b.resource_id = machine.equipment_id
        """,
        "slvr_material_inventory_position": """
            SELECT b.*, site.site_code AS canonical_site_id,
                   product.product_number AS canonical_product_id
            FROM brnz_material_inventory_position b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON b.product_number = product.product_number
        """,
        "slvr_inbound_receipt": """
            SELECT b.*, site.site_code AS canonical_site_id,
                   product.product_number AS canonical_product_id
            FROM brnz_inbound_receipt b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON b.product_number = product.product_number
        """,
        "slvr_shipment": """
            SELECT b.*, site.site_code AS canonical_site_id,
                   product.product_number AS canonical_product_id
            FROM brnz_shipment b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON b.product_number = product.product_number
        """,
        "slvr_safety_stock_policy": """
            SELECT b.*, site.site_code AS canonical_site_id,
                   product.product_number AS canonical_product_id
            FROM brnz_safety_stock_policy b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON b.product_number = product.product_number
        """,
        "slvr_service_target": """
            SELECT b.*, site.site_code AS canonical_site_id,
                   product.product_number AS canonical_product_id
            FROM brnz_service_target b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON b.product_number = product.product_number
        """,
        "slvr_equipment_cost_reference": """
            SELECT b.*, machine.equipment_id AS canonical_equipment_id
            FROM brnz_equipment_cost_reference b
            LEFT JOIN reference.canonical.machine machine
              ON b.equipment_id = machine.equipment_id
        """,
        "slvr_lot_route_movement_event": """
            SELECT b.*, site.site_code AS canonical_site_id,
                   product.product_number AS canonical_product_id,
                   machine.equipment_id AS canonical_machine_id,
                   CAST(b.route_id AS VARCHAR) AS canonical_route_id,
                   CAST(b.route_step_id AS VARCHAR) AS canonical_route_step_id
            FROM brnz_lot_route_movement_event b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON b.product_number = product.product_number
            LEFT JOIN reference.canonical.machine machine
              ON b.machine_id = machine.equipment_id
        """,
        "slvr_production_schedule": """
            SELECT b.*, site.site_code AS canonical_site_id,
                   product.product_number AS canonical_product_id
            FROM brnz_production_schedule b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON b.product_number = product.product_number
        """,
        "slvr_npi_program": """
            SELECT b.*, CAST(b.program_id AS VARCHAR) AS canonical_program_id,
                   site.site_code AS canonical_site_id,
                   product.product_number AS canonical_product_id
            FROM brnz_npi_program b
            LEFT JOIN reference.canonical.site site ON b.lead_site_code = site.site_code
            LEFT JOIN reference.canonical.product product
              ON b.product_number = product.product_number
        """,
        "slvr_npi_stage_gate": """
            SELECT b.*, CAST(b.program_id AS VARCHAR) AS canonical_program_id
            FROM brnz_npi_stage_gate b
        """,
        "slvr_npi_milestone": """
            SELECT b.*, CAST(b.program_id AS VARCHAR) AS canonical_program_id
            FROM brnz_npi_milestone b
        """,
        "slvr_npi_qualification_evidence": """
            SELECT b.*, CAST(b.program_id AS VARCHAR) AS canonical_program_id,
                   site.site_code AS canonical_site_id
            FROM brnz_npi_qualification_evidence b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
        """,
        "slvr_npi_pilot_lot": """
            SELECT b.*, CAST(b.program_id AS VARCHAR) AS canonical_program_id,
                   site.site_code AS canonical_site_id
            FROM brnz_npi_pilot_lot b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
        """,
        "slvr_npi_tooling_readiness": """
            SELECT b.*, CAST(b.program_id AS VARCHAR) AS canonical_program_id,
                   site.site_code AS canonical_site_id
            FROM brnz_npi_tooling_readiness b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
        """,
        "slvr_npi_ramp_target": """
            SELECT b.*, CAST(b.program_id AS VARCHAR) AS canonical_program_id,
                   site.site_code AS canonical_site_id
            FROM brnz_npi_ramp_target b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
        """,
        "slvr_npi_ramp_actual": """
            SELECT b.*, CAST(b.program_id AS VARCHAR) AS canonical_program_id,
                   site.site_code AS canonical_site_id
            FROM brnz_npi_ramp_actual b
            LEFT JOIN reference.canonical.site site ON b.site_code = site.site_code
        """,
        "slvr_npi_risk": """
            SELECT b.*, CAST(b.program_id AS VARCHAR) AS canonical_program_id
            FROM brnz_npi_risk b
        """,
        "slvr_npi_owner": """
            SELECT b.*, CAST(b.program_id AS VARCHAR) AS canonical_program_id
            FROM brnz_npi_owner b
        """,
        "slvr_npi_status_history": """
            SELECT b.*, CAST(b.program_id AS VARCHAR) AS canonical_program_id
            FROM brnz_npi_status_history b
        """,
    }
    counts: dict[str, int] = {}
    for table, query in statements.items():
        connection.execute(f'DROP TABLE IF EXISTS "{table}"')
        connection.execute(
            f"""
            CREATE TABLE "{table}" AS
            SELECT source.*, ? AS silver_created_at
            FROM ({query}) source
            """,
            [created_at],
        )
        counts[table] = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

    required = {
        "slvr_customer_order": ["canonical_site_id", "canonical_product_id"],
        "slvr_backlog_position": ["canonical_site_id", "canonical_product_id"],
        "slvr_constrained_production_plan": [
            "canonical_site_id",
            "canonical_product_id",
        ],
        "slvr_shared_resource_allocation": [
            "canonical_site_id",
            "canonical_product_id",
            "canonical_resource_id",
        ],
        "slvr_material_inventory_position": [
            "canonical_site_id",
            "canonical_product_id",
        ],
        "slvr_inbound_receipt": ["canonical_site_id", "canonical_product_id"],
        "slvr_shipment": ["canonical_site_id", "canonical_product_id"],
        "slvr_safety_stock_policy": ["canonical_site_id", "canonical_product_id"],
        "slvr_service_target": ["canonical_site_id", "canonical_product_id"],
        "slvr_equipment_cost_reference": ["canonical_equipment_id"],
        "slvr_lot_route_movement_event": [
            "canonical_site_id",
            "canonical_product_id",
            "canonical_machine_id",
        ],
        "slvr_production_schedule": ["canonical_site_id", "canonical_product_id"],
        "slvr_npi_program": [
            "canonical_program_id",
            "canonical_site_id",
            "canonical_product_id",
        ],
    }
    for table, columns in required.items():
        _require_complete_mapping(connection, table, columns)

    orphan_programs = connection.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT program_id FROM slvr_npi_stage_gate
            UNION ALL SELECT program_id FROM slvr_npi_milestone
            UNION ALL SELECT program_id FROM slvr_npi_qualification_evidence
            UNION ALL SELECT program_id FROM slvr_npi_pilot_lot
            UNION ALL SELECT program_id FROM slvr_npi_tooling_readiness
            UNION ALL SELECT program_id FROM slvr_npi_ramp_target
            UNION ALL SELECT program_id FROM slvr_npi_ramp_actual
            UNION ALL SELECT program_id FROM slvr_npi_risk
            UNION ALL SELECT program_id FROM slvr_npi_owner
            UNION ALL SELECT program_id FROM slvr_npi_status_history
        ) child
        LEFT JOIN slvr_npi_program program USING (program_id)
        WHERE program.program_id IS NULL
        """
    ).fetchone()[0]
    if orphan_programs:
        raise ValueError(f"NPI facts contain {orphan_programs} orphan program references")
    return counts


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
    counts.update(build_planning_foundation(connection, run_id, created_at))

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
