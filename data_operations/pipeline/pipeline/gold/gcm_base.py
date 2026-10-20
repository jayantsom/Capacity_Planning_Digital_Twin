"""
Gold layer: GCM Base Join.
...
"""

from capacity_twin_core.logging import logger


def build_gcm_base(duck_conn) -> int:
    logger.info("  Building gold_gcm_base")

    duck_conn.execute("DROP TABLE IF EXISTS gold_gcm_base")

    duck_conn.execute("""
        CREATE TABLE gold_gcm_base AS

        WITH demand_rollup AS (
            SELECT
                site_code,
                product_number,
                month_key,
                snapshot_id,
                snapshot_date,
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
                snapshot_id,
                snapshot_date,
                data_type
        ),

        all_demand AS (
            SELECT
                d.site_code,
                d.product_number,
                p.product_family,
                p.platform,
                p.product_status,
                d.month_key,
                d.snapshot_id,
                d.snapshot_date,
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
                ad.snapshot_id,
                ad.snapshot_date,
                ad.data_type,

                -- Product
                ad.product_number,
                ad.product_description,
                ad.product_family,
                ad.platform,
                ad.product_status,
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

                -- GCM-MI join key
                rs.factory_code || '|' || ttt.test_category_id
                    || '|' || ad.product_number     AS gcm_mi_join_key

            FROM all_demand ad

            JOIN slvr_tgt_test_time ttt
                ON  ad.site_code      = ttt.site_code
                AND ad.product_number  = ttt.product_number
                AND ad.month_key       = ttt.month_key
                AND ad.snapshot_id     = ttt.snapshot_id
                AND ttt.is_valid       = true

            LEFT JOIN slvr_tgt_yield ty
                ON  ad.site_code      = ty.site_code
                AND ad.product_number  = ty.product_number
                AND ttt.test_type      = ty.test_type
                AND ad.month_key       = ty.month_key
                AND ad.snapshot_id     = ty.snapshot_id
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
                CAST(month_key AS VARCHAR)  || '|' || snapshot_id
            )                           AS gcm_pk,
            *
        FROM gcm_joined
    """)

    for col in ["month_key", "site_code", "product_number",
                "test_type", "snapshot_id", "gcm_mi_join_key"]:
        duck_conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_gold_gcm_{col}
            ON gold_gcm_base ({col})
        """)

    count = duck_conn.execute(
        "SELECT COUNT(*) FROM gold_gcm_base"
    ).fetchone()[0]
    logger.info(f"    gold_gcm_base: {count:,} rows")
    return count