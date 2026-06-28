"""
Gold layer: GCM Base Join.
...
"""

from src.utils.logger import logger
from src.pipeline.gold.utils import write_gold_table


def build_gcm_base(duck_conn) -> int:
    logger.info("  Building gold_gcm_base")

    duck_conn.execute("DROP TABLE IF EXISTS gold_gcm_base")

    duck_conn.execute("""
        CREATE TABLE gold_gcm_base AS

        WITH demand AS (
            SELECT
                d.site_code,
                d.product_number,
                d.product_family,
                d.platform,
                d.product_status,
                d.month_key,
                d.snapshot_id,
                d.snapshot_date,
                d.forecast_source,
                d.data_type,
                d.demand_qty,
                p.is_parent,
                p.has_children,
                p.product_description,
                p.product_type,
                p.product_poc
            FROM slvr_dmnd_forecast d
            LEFT JOIN slvr_prod_master p
                ON d.product_number = p.product_number
        ),

        demand_with_children AS (
            SELECT
                d.site_code,
                h.child_product_number          AS product_number,
                pm.product_family,
                pm.platform,
                pm.product_status,
                d.month_key,
                d.snapshot_id,
                d.snapshot_date,
                d.forecast_source,
                d.data_type,
                d.demand_qty * h.child_quantity AS demand_qty,
                d.demand_qty                    AS parent_demand_qty,
                h.child_quantity,
                0                               AS is_parent,
                0                               AS has_children,
                pm.product_description,
                pm.product_type,
                pm.product_poc,
                d.product_number                AS parent_product_number
            FROM demand d
            JOIN slvr_prod_hierarchy h
                ON d.product_number = h.parent_product_number
            JOIN slvr_prod_master pm
                ON h.child_product_number = pm.product_number
            WHERE d.is_parent = 1
        ),

        all_demand AS (
            SELECT
                site_code,
                product_number,
                product_family,
                platform,
                product_status,
                month_key,
                snapshot_id,
                snapshot_date,
                forecast_source,
                data_type,
                demand_qty,
                demand_qty          AS parent_demand_qty,
                1.0                 AS child_quantity,
                is_parent,
                has_children,
                product_description,
                product_type,
                product_poc,
                product_number      AS parent_product_number
            FROM demand

            UNION ALL

            SELECT
                site_code,
                product_number,
                product_family,
                platform,
                product_status,
                month_key,
                snapshot_id,
                snapshot_date,
                forecast_source,
                data_type,
                demand_qty,
                parent_demand_qty,
                child_quantity,
                is_parent,
                has_children,
                product_description,
                product_type,
                product_poc,
                parent_product_number
            FROM demand_with_children
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
                ad.parent_product_number,
                ad.child_quantity,

                -- Demand
                ad.demand_qty               AS effective_demand_qty,
                ad.parent_demand_qty,

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

            LEFT JOIN slvr_site_equip_inv ei
                ON  ad.site_code  = ei.site_code
                AND ttt.test_type = ei.test_type
                AND ad.month_key  = ei.month_key

            LEFT JOIN slvr_site_soft ss
                ON  ad.site_code  = ss.site_code
                AND ad.month_key  = ss.month_key

            LEFT JOIN slvr_ref_site rs
                ON ad.site_code = rs.site_code

            LEFT JOIN slvr_ref_test_type rtt
                ON ttt.test_type = rtt.test_type

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