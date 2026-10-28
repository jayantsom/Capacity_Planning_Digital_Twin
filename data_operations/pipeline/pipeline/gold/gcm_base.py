"""
Gold layer: GCM Base Join.
...
"""

from capacity_twin_core.logging import logger


def _has_governed_resource_contracts(duck_conn) -> bool:
    required = {"slvr_product_route", "slvr_route_step", "slvr_resource_contract"}
    present = {
        row[0]
        for row in duck_conn.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    return required <= present


def _build_governed_gcm_base(duck_conn) -> int:
    """Build route-step demand with governed resource allocation and workload units."""
    duck_conn.execute(
        """
        CREATE TABLE gold_gcm_base AS
        WITH demand_rollup AS (
            SELECT
                site_code,
                product_number,
                month_key,
                planning_version_id,
                plan_as_of_date,
                data_type,
                SUM(independent_demand_qty) AS independent_demand_qty,
                SUM(dependent_demand_qty) AS dependent_demand_qty,
                SUM(total_requirement_qty) AS route_step_demand_qty,
                string_agg(DISTINCT demand_class, ',' ORDER BY demand_class)
                    AS demand_classes,
                string_agg(
                    DISTINCT parent_product_number, ',' ORDER BY parent_product_number
                ) FILTER (WHERE parent_product_number IS NOT NULL)
                    AS parent_product_numbers
            FROM slvr_demand_requirement
            WHERE is_valid
            GROUP BY ALL
        ),
        governed AS (
            SELECT
                d.*,
                product.product_description,
                product.product_family,
                product.platform,
                product.product_type,
                product.product_poc,
                product.is_parent,
                product.has_children,
                route.route_id,
                step.route_step_id,
                step.step_sequence AS route_step_sequence,
                step.full_demand_required,
                step.test_type,
                resource.qualification_id,
                resource.resource_id AS equipment_id,
                resource.resource_kind AS equipment_type,
                resource.resource_behavior,
                resource.pool_id,
                resource.pool_behavior,
                resource.paired_fixture_resource_id,
                resource.handler_resource_id,
                resource.fixture_slots_required,
                resource.tester_channels,
                resource.enabled_licensed_ports,
                resource.tester_fixture_slots,
                resource.fixture_cavities,
                resource.handler_sockets,
                resource.fixtures_required_per_system,
                resource.execution_mode,
                resource.batch_cycle_time_sec,
                resource.changeover_time_sec,
                resource.parallel_efficiency,
                GREATEST(COALESCE(resource.effective_parallel_duts, 1), 1)
                    AS effective_parallel_duts
            FROM demand_rollup d
            JOIN slvr_prod_master product
              ON d.product_number = product.product_number AND product.is_valid
            JOIN slvr_product_route route
              ON d.product_number = route.product_number AND route.is_valid
             AND d.plan_as_of_date BETWEEN
                 CAST(route.effective_start_date AS DATE)
                 AND CAST(route.effective_end_date AS DATE)
            JOIN slvr_route_step step
              ON route.route_id = step.route_id AND step.is_valid
            JOIN slvr_resource_contract resource
              ON d.site_code = resource.site_code
             AND d.product_number = resource.product_number
             AND step.test_type = resource.test_type
             AND d.plan_as_of_date BETWEEN
                 CAST(resource.effective_start_date AS DATE)
                 AND CAST(resource.effective_end_date AS DATE)
            WHERE d.route_step_demand_qty > 0
        ),
        enriched AS (
            SELECT
                site.factory_code,
                governed.*,
                site.region,
                site.supplier_name,
                site.country,
                test_time.test_category_id,
                test_type.test_category_name,
                test_time.responsible_person,
                test_time.target_test_time_sec,
                yield.target_yield,
                yield.is_forward_filled AS yield_forward_filled,
                inventory.handling_time_sec,
                inventory.qualification_time_sec,
                inventory.cycle_time_sec,
                inventory.utilization_rate,
                inventory.yield_retest_1,
                inventory.yield_retest_2_plus,
                inventory.retest_quote,
                inventory.equip_qty_available,
                fixture_inventory.equip_qty_available AS paired_fixture_qty_available,
                soft.wd_normal AS working_days_normal,
                soft.shifts_normal AS shifts_per_day_normal,
                soft.hrs_normal AS hours_per_shift_normal,
                soft.wd_max AS working_days_max,
                soft.shifts_max AS shifts_per_day_max,
                soft.hrs_max AS hours_per_shift_max,
                soft.allowance_pct,
                soft.productivity_pct,
                COUNT(*) OVER (
                    PARTITION BY governed.site_code, governed.product_number,
                                 governed.month_key, governed.planning_version_id,
                                 governed.route_step_id
                ) AS qualified_resource_count
            FROM governed
            JOIN slvr_tgt_test_time test_time
              ON governed.site_code = test_time.site_code
             AND governed.product_number = test_time.product_number
             AND governed.test_type = test_time.test_type
             AND governed.month_key = test_time.month_key
             AND governed.planning_version_id = test_time.planning_version_id
             AND test_time.is_valid
            JOIN slvr_tgt_yield yield
              ON governed.site_code = yield.site_code
             AND governed.product_number = yield.product_number
             AND governed.test_type = yield.test_type
             AND governed.month_key = yield.month_key
             AND governed.planning_version_id = yield.planning_version_id
             AND yield.is_valid
            JOIN slvr_site_equip_inv inventory
              ON governed.site_code = inventory.site_code
             AND governed.equipment_id = inventory.test_equipment_id
             AND governed.month_key = inventory.month_key
             AND inventory.is_valid
            LEFT JOIN slvr_site_equip_inv fixture_inventory
              ON governed.site_code = fixture_inventory.site_code
             AND governed.paired_fixture_resource_id =
                 fixture_inventory.test_equipment_id
             AND governed.month_key = fixture_inventory.month_key
             AND fixture_inventory.is_valid
            JOIN slvr_site_soft soft
              ON governed.site_code = soft.site_code
             AND governed.month_key = soft.month_key
             AND soft.is_valid
            JOIN slvr_ref_site site
              ON governed.site_code = site.site_code AND site.is_valid
            JOIN slvr_ref_test_type test_type
              ON governed.test_type = test_type.test_type AND test_type.is_valid
            WHERE test_time.target_test_time_sec > 0
              AND yield.target_yield > 0
        ),
        calculated AS (
            SELECT
                *,
                CASE
                    WHEN resource_behavior IN ('ALTERNATIVE_POOL', 'SHARED_POOL')
                    THEN route_step_demand_qty / qualified_resource_count
                    ELSE route_step_demand_qty
                END AS effective_demand_qty,
                COALESCE(
                    batch_cycle_time_sec,
                    cycle_time_sec,
                    target_test_time_sec + COALESCE(handling_time_sec, 0)
                ) + COALESCE(changeover_time_sec, 0)
                    / GREATEST(effective_parallel_duts, 1)
                    AS governed_cycle_time_sec,
                LEAST(
                    equip_qty_available,
                    CASE
                        WHEN resource_behavior = 'PAIRED_FIXTURE'
                        THEN COALESCE(
                            paired_fixture_qty_available
                                / NULLIF(fixtures_required_per_system, 0),
                            equip_qty_available
                        )
                        ELSE equip_qty_available
                    END
                ) AS constrained_resource_qty
            FROM enriched
        )
        SELECT
            md5(
                site_code || '|' || product_number || '|' || route_step_id || '|' ||
                equipment_id || '|' || CAST(month_key AS VARCHAR) || '|' ||
                planning_version_id
            ) AS gcm_pk,
            * EXCLUDE (equip_qty_available),
            constrained_resource_qty AS equip_qty_available,
            effective_demand_qty * governed_cycle_time_sec
                / NULLIF(effective_parallel_duts * COALESCE(parallel_efficiency, 1), 0)
                AS workload_seconds,
            effective_demand_qty * governed_cycle_time_sec
                / NULLIF(
                    effective_parallel_duts * COALESCE(parallel_efficiency, 1) * 3600.0,
                    0
                )
                AS workload_resource_hours,
            constrained_resource_qty * working_days_normal *
                shifts_per_day_normal * hours_per_shift_normal *
                (1 - allowance_pct) * productivity_pct * utilization_rate
                AS available_resource_hours_normal,
            constrained_resource_qty * working_days_max *
                shifts_per_day_max * hours_per_shift_max *
                (1 - allowance_pct) * productivity_pct * utilization_rate
                AS available_resource_hours_maximum,
            factory_code || '|' || test_category_id || '|' || product_number
                AS gcm_machine_join_key
        FROM calculated
        """
    )
    for column in (
        "month_key",
        "site_code",
        "product_number",
        "route_step_id",
        "test_type",
        "planning_version_id",
        "resource_behavior",
    ):
        duck_conn.execute(
            f"CREATE INDEX idx_gold_gcm_{column} ON gold_gcm_base ({column})"
        )
    count = int(duck_conn.execute("SELECT COUNT(*) FROM gold_gcm_base").fetchone()[0])
    logger.info(f"    gold_gcm_base: {count:,} governed rows")
    return count


def build_gcm_base(duck_conn) -> int:
    logger.info("  Building gold_gcm_base")

    duck_conn.execute("DROP TABLE IF EXISTS gold_gcm_base")

    if _has_governed_resource_contracts(duck_conn):
        return _build_governed_gcm_base(duck_conn)

    duck_conn.execute("""
        CREATE TABLE gold_gcm_base AS

        WITH demand_rollup AS (
            SELECT
                site_code,
                product_number,
                month_key,
                planning_version_id,
                plan_as_of_date,
                data_type,
                SUM(independent_demand_qty) AS independent_demand_qty,
                SUM(dependent_demand_qty) AS dependent_demand_qty,
                SUM(total_requirement_qty) AS demand_qty,
                string_agg(
                    DISTINCT demand_class,
                    ',' ORDER BY demand_class
                ) AS demand_classes,
                string_agg(
                    DISTINCT parent_product_number,
                    ',' ORDER BY parent_product_number
                ) FILTER (WHERE parent_product_number IS NOT NULL)
                    AS parent_product_numbers
            FROM slvr_demand_requirement
            WHERE is_valid
            GROUP BY
                site_code,
                product_number,
                month_key,
                planning_version_id,
                plan_as_of_date,
                data_type
        ),

        all_demand AS (
            SELECT
                d.site_code,
                d.product_number,
                p.product_family,
                p.platform,
                d.month_key,
                d.planning_version_id,
                d.plan_as_of_date,
                'SYNTHETIC_REQUIREMENT' AS forecast_source,
                d.data_type,
                d.demand_qty,
                d.independent_demand_qty,
                d.dependent_demand_qty,
                d.demand_classes,
                d.parent_product_numbers,
                p.is_parent,
                p.has_children,
                p.product_description,
                p.product_type,
                p.product_poc
            FROM demand_rollup d
            JOIN slvr_prod_master p
                ON d.product_number = p.product_number
                AND p.is_valid
        ),

        gcm_joined AS (
            SELECT
                -- Keys
                rs.factory_code,
                ad.site_code,
                ad.month_key,
                ad.planning_version_id,
                ad.plan_as_of_date,
                ad.data_type,

                -- Product
                ad.product_number,
                ad.product_description,
                ad.product_family,
                ad.platform,
                ad.product_type,
                ad.product_poc,
                ad.is_parent,
                ad.has_children,
                ad.parent_product_numbers,

                -- Demand
                ad.demand_qty               AS effective_demand_qty,
                ad.independent_demand_qty,
                ad.dependent_demand_qty,
                ad.demand_classes,

                -- Test
                ttt.test_type,
                ttt.test_category_id,
                rtt.test_category_name,
                ttt.responsible_person,

                -- Target test time
                ttt.target_test_time_sec,

                -- Target yield
                COALESCE(ty.target_yield, 0.85)     AS target_yield,
                ty.is_forward_filled                AS yield_forward_filled,

                -- Equipment
                ei.test_equipment_id                AS equipment_id,
                ei.equipment_type,
                ei.handling_time_sec,
                ei.qualification_time_sec,
                ei.cycle_time_sec,
                COALESCE(ei.utilization_rate, 0.85) AS utilization_rate,
                ei.yield_retest_1,
                ei.yield_retest_2_plus,
                ei.retest_quote,
                ei.equip_qty_available,

                -- Site soft (Normal)
                ss.wd_normal            AS working_days_normal,
                ss.shifts_normal        AS shifts_per_day_normal,
                ss.hrs_normal           AS hours_per_shift_normal,

                -- Site soft (Maximum)
                ss.wd_max               AS working_days_max,
                ss.shifts_max           AS shifts_per_day_max,
                ss.hrs_max              AS hours_per_shift_max,

                -- Allowance + productivity
                COALESCE(ss.allowance_pct,    0.10) AS allowance_pct,
                COALESCE(ss.productivity_pct, 0.85) AS productivity_pct,

                -- Region
                rs.region,
                rs.supplier_name,
                rs.country,

                -- GCM-Machine join key
                rs.factory_code || '|' || ttt.test_category_id
                    || '|' || ad.product_number     AS gcm_machine_join_key

            FROM all_demand ad

            JOIN slvr_tgt_test_time ttt
                ON  ad.site_code      = ttt.site_code
                AND ad.product_number  = ttt.product_number
                AND ad.month_key       = ttt.month_key
                AND ad.planning_version_id     = ttt.planning_version_id
                AND ttt.is_valid       = true

            LEFT JOIN slvr_tgt_yield ty
                ON  ad.site_code      = ty.site_code
                AND ad.product_number  = ty.product_number
                AND ttt.test_type      = ty.test_type
                AND ad.month_key       = ty.month_key
                AND ad.planning_version_id     = ty.planning_version_id
                AND ty.is_valid         = true

            LEFT JOIN slvr_site_equip_inv ei
                ON  ad.site_code  = ei.site_code
                AND ttt.test_type = ei.test_type
                AND ad.month_key  = ei.month_key
                AND ei.is_valid    = true

            LEFT JOIN slvr_site_soft ss
                ON  ad.site_code  = ss.site_code
                AND ad.month_key  = ss.month_key
                AND ss.is_valid    = true

            LEFT JOIN slvr_ref_site rs
                ON ad.site_code = rs.site_code
                AND rs.is_valid

            LEFT JOIN slvr_ref_test_type rtt
                ON ttt.test_type = rtt.test_type
                AND rtt.is_valid

            -- Filter in the join layer using demand_qty (before alias)
            WHERE ad.demand_qty > 0
              AND ttt.target_test_time_sec IS NOT NULL
              AND ttt.target_test_time_sec > 0
        )

        SELECT
            md5(
                site_code || '|' || product_number || '|' ||
                COALESCE(test_type, '')     || '|' ||
                COALESCE(equipment_id, '')  || '|' ||
                CAST(month_key AS VARCHAR)  || '|' || planning_version_id
            )                           AS gcm_pk,
            *
        FROM gcm_joined
    """)

    for col in [
        "month_key",
        "site_code",
        "product_number",
        "test_type",
        "planning_version_id",
        "gcm_machine_join_key",
    ]:
        duck_conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_gold_gcm_{col}
            ON gold_gcm_base ({col})
        """)

    count = duck_conn.execute("SELECT COUNT(*) FROM gold_gcm_base").fetchone()[0]
    logger.info(f"    gold_gcm_base: {count:,} rows")
    return count
