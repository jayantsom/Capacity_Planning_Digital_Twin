"""
Gold layer: Analytics tables.
Built from gold_gcm_base and gold_cap_* using DuckDB SQL.
DuckDB is faster than Spark for these aggregation patterns.
"""

from src.utils.logger import logger
from src.pipeline.gold.utils import write_gold_table


def build_demand_vs_capacity(duck_conn) -> int:
    logger.info("  Building gold_dmnd_vs_cap")
    duck_conn.execute("DROP TABLE IF EXISTS gold_dmnd_vs_cap")
    duck_conn.execute("""
        CREATE TABLE gold_dmnd_vs_cap AS
        SELECT
            md5(
                n.site_code || '|' || n.product_number || '|' ||
                n.test_type  || '|' || n.equipment_id  || '|' ||
                CAST(n.month_key AS VARCHAR) || '|' || n.snapshot_id ||
                '|' || n.capacity_mode || '|' || n.retest_type
            )                           AS gap_pk,
            n.site_code,
            n.factory_code,
            n.month_key,
            n.snapshot_id,
            n.product_number,
            n.product_family,
            n.platform,
            n.product_status,
            n.test_type,
            n.equipment_id,
            n.equipment_type,
            n.capacity_mode,
            n.retest_type,
            n.effective_demand_qty      AS demand_qty,
            n.capacity_qty,
            n.gap_qty,
            n.gap_pct,
            n.utilization_pct,
            n.is_bottleneck,
            n.is_excess,
            n.excess_capacity_units,
            n.investment_need_units,
            n.bottleneck_severity,
            -- Flexibility: how much surge normal→max provides
            CASE
                WHEN n.capacity_mode = 'NORMAL' AND m.capacity_qty > 0
                THEN (m.capacity_qty - n.capacity_qty) / n.capacity_qty
                ELSE NULL
            END                         AS flexibility_pct
        FROM gold_cap_normal n
        LEFT JOIN gold_cap_maximum m
            ON  n.gcm_pk      = m.gcm_pk
            AND n.retest_type = m.retest_type
    """)
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gold_dvc_month
        ON gold_dmnd_vs_cap (month_key)
    """)
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gold_dvc_site
        ON gold_dmnd_vs_cap (site_code)
    """)
    count = duck_conn.execute(
        "SELECT COUNT(*) FROM gold_dmnd_vs_cap"
    ).fetchone()[0]
    logger.info(f"    gold_dmnd_vs_cap: {count:,} rows")
    return count


def build_bottleneck_table(duck_conn) -> int:
    logger.info("  Building gold_bottleneck")
    duck_conn.execute("DROP TABLE IF EXISTS gold_bottleneck")
    duck_conn.execute("""
        CREATE TABLE gold_bottleneck AS
        SELECT
            md5(
                site_code || '|' || test_type || '|' ||
                equipment_type || '|' ||
                CAST(month_key AS VARCHAR) || '|' ||
                snapshot_id || '|' || capacity_mode || '|' || retest_type
            )                               AS bottleneck_pk,
            site_code,
            month_key,
            snapshot_id,
            capacity_mode,
            retest_type,
            test_type,
            equipment_type,
            -- Severity is the worst (most critical) across products
            -- at this site-month-test_type
            CASE
                WHEN MIN(gap_pct) < -0.15 THEN 'CRITICAL'
                WHEN MIN(gap_pct) < -0.08 THEN 'HIGH'
                WHEN MIN(gap_pct) < -0.03 THEN 'MEDIUM'
                WHEN MIN(gap_pct) <  0.00 THEN 'LOW'
                WHEN MIN(gap_pct) <  0.05 THEN 'BALANCED'
                ELSE                           'EXCESS'
            END                             AS bottleneck_severity,
            MIN(gap_qty)                    AS worst_gap_qty,
            SUM(CASE WHEN investment_need_units > 0
                     THEN investment_need_units ELSE 0 END)
                                            AS total_investment_need_units,
            COUNT(DISTINCT product_number)  AS affected_products,
            SUM(demand_qty)                 AS affected_demand_qty,
            MIN(gap_pct)                    AS min_gap_pct,
            AVG(gap_pct)                    AS avg_gap_pct,
            AVG(utilization_pct)            AS avg_utilization_pct
        FROM gold_dmnd_vs_cap
        GROUP BY
            site_code, month_key, snapshot_id, capacity_mode,
            retest_type, test_type, equipment_type
    """)
    count = duck_conn.execute(
        "SELECT COUNT(*) FROM gold_bottleneck"
    ).fetchone()[0]
    logger.info(f"    gold_bottleneck: {count:,} rows")
    return count


def build_oee_metrics(duck_conn) -> int:
    logger.info("  Building gold_oee_metrics")
    duck_conn.execute("DROP TABLE IF EXISTS gold_oee_metrics")
    duck_conn.execute("""
        CREATE TABLE gold_oee_metrics AS
        WITH daily_agg AS (
            SELECT
                mi.factory_code,
                mi.site_code,
                mi.test_category_id,
                mi.test_type,
                mi.month_key,
                -- Availability: fraction of time equipment was running
                -- proxy: 1 - (downtime / total_possible_seconds)
                -- total_possible: 8hr shift × 3600
                1.0 - (
                    AVG(mi.equipment_downtime_avg) /
                    NULLIF(8.0 * 3600, 0)
                )                                       AS availability_pct,
                -- Performance: actual vs ideal throughput
                AVG(mi.actual_throughput) /
                NULLIF(
                    AVG(mi.actual_throughput) +
                    AVG(mi.idle_time_avg) / 60.0,
                    0
                )                                       AS performance_pct,
                -- Quality: actual yield
                AVG(mi.yield_avg)                       AS quality_pct,
                AVG(mi.actual_throughput)               AS actual_throughput,
                SUM(mi.passed_qty_sum)                  AS total_passed,
                SUM(mi.total_qty_sum)                   AS total_produced,
                AVG(mi.equipment_downtime_avg) / 3600.0 AS avg_downtime_hr
            FROM slvr_mi_execution mi
            WHERE mi.yield_avg IS NOT NULL
            GROUP BY
                mi.factory_code, mi.site_code,
                mi.test_category_id, mi.test_type, mi.month_key
        )
        SELECT
            md5(
                factory_code || '|' || test_category_id || '|' ||
                CAST(month_key AS VARCHAR)
            )                           AS oee_pk,
            factory_code,
            site_code,
            test_category_id,
            test_type,
            month_key,
            ROUND(LEAST(1.0, GREATEST(0.0,
                COALESCE(availability_pct, 0.85))), 4)  AS availability_pct,
            ROUND(LEAST(1.0, GREATEST(0.0,
                COALESCE(performance_pct, 0.85))), 4)   AS performance_pct,
            ROUND(LEAST(1.0, GREATEST(0.0,
                COALESCE(quality_pct, 0.85))), 4)       AS quality_pct,
            ROUND(
                LEAST(1.0, GREATEST(0.0,
                    COALESCE(availability_pct, 0.85))) *
                LEAST(1.0, GREATEST(0.0,
                    COALESCE(performance_pct, 0.85))) *
                LEAST(1.0, GREATEST(0.0,
                    COALESCE(quality_pct, 0.85))), 4)   AS oee_pct,
            actual_throughput,
            total_passed,
            total_produced,
            avg_downtime_hr
        FROM daily_agg
    """)
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gold_oee_month
        ON gold_oee_metrics (month_key)
    """)
    count = duck_conn.execute(
        "SELECT COUNT(*) FROM gold_oee_metrics"
    ).fetchone()[0]
    logger.info(f"    gold_oee_metrics: {count:,} rows")
    return count


def build_forecast_accuracy(duck_conn) -> int:
    logger.info("  Building gold_forecast_accuracy")
    duck_conn.execute("DROP TABLE IF EXISTS gold_forecast_accuracy")
    duck_conn.execute("""
        CREATE TABLE gold_forecast_accuracy AS
        WITH actuals AS (
            SELECT
                site_code, product_number, month_key,
                demand_qty AS actual_qty
            FROM slvr_dmnd_forecast
            WHERE data_type = 'ACTUAL'
              AND snapshot_id = 'snap-2023-01-planning-cycle'
        ),
        forecasts AS (
            SELECT
                site_code, product_number, month_key,
                demand_qty AS forecast_qty,
                snapshot_id, snapshot_date, forecast_source
            FROM slvr_dmnd_forecast
            WHERE data_type = 'ACTUAL'
              AND snapshot_id != 'snap-2023-01-planning-cycle'
        )
        SELECT
            md5(
                f.site_code || '|' || f.product_number || '|' ||
                CAST(f.month_key AS VARCHAR) || '|' || f.snapshot_id
            )                               AS fa_pk,
            f.site_code,
            f.product_number,
            f.month_key,
            f.snapshot_id,
            f.snapshot_date,
            f.forecast_source,
            f.forecast_qty,
            a.actual_qty,
            ABS(f.forecast_qty - a.actual_qty)
                                            AS abs_error,
            CASE
                WHEN a.actual_qty > 0
                THEN ABS(f.forecast_qty - a.actual_qty) / a.actual_qty
                ELSE NULL
            END                             AS pct_error,
            (f.forecast_qty - a.actual_qty) AS bias
        FROM forecasts f
        JOIN actuals a
            ON  f.site_code      = a.site_code
            AND f.product_number  = a.product_number
            AND f.month_key       = a.month_key
        WHERE a.actual_qty > 0
    """)
    count = duck_conn.execute(
        "SELECT COUNT(*) FROM gold_forecast_accuracy"
    ).fetchone()[0]
    logger.info(f"    gold_forecast_accuracy: {count:,} rows")
    return count


def build_actual_capacity(duck_conn) -> int:
    logger.info("  Building gold_cap_actual")
    duck_conn.execute("DROP TABLE IF EXISTS gold_cap_actual")
    duck_conn.execute("""
        CREATE TABLE gold_cap_actual AS
        WITH mi_monthly AS (
            SELECT
                factory_code,
                site_code,
                product_number,
                test_category_id,
                test_type,
                month_key,
                -- Composite join key matching GCM format
                factory_code || '|' || test_category_id
                    || '|' || product_number       AS gcm_mi_join_key,
                SUM(passed_qty_sum)                AS actual_passed_qty,
                SUM(failed_qty_sum)                AS actual_failed_qty,
                SUM(total_qty_sum)                 AS actual_total_qty,
                AVG(yield_avg)                     AS actual_yield_avg,
                AVG(final_test_yield_avg)          AS actual_final_yield_avg,
                AVG(test_duration_avg)             AS actual_test_duration_avg,
                AVG(handling_time_avg)             AS actual_handling_time_avg,
                AVG(actual_throughput)             AS actual_throughput_avg,
                AVG(equipment_downtime_avg)        AS actual_downtime_avg
            FROM slvr_mi_execution
            WHERE yield_avg IS NOT NULL
            GROUP BY
                factory_code, site_code, product_number,
                test_category_id, test_type, month_key
        )
        SELECT
            md5(
                g.gcm_mi_join_key || '|' || CAST(m.month_key AS VARCHAR)
            )                               AS cap_act_pk,
            g.gcm_mi_join_key,
            g.site_code,
            g.factory_code,
            m.month_key,
            g.product_number,
            m.test_category_id,
            m.test_type,
            m.actual_passed_qty,
            m.actual_failed_qty,
            m.actual_total_qty,
            m.actual_yield_avg,
            m.actual_final_yield_avg,
            m.actual_test_duration_avg,
            m.actual_handling_time_avg,
            m.actual_throughput_avg,
            m.actual_downtime_avg,
            -- Variance vs target
            g.target_yield,
            g.target_test_time_sec,
            m.actual_yield_avg - g.target_yield
                                            AS yield_variance,
            m.actual_test_duration_avg - g.target_test_time_sec
                                            AS test_time_variance_sec
        FROM mi_monthly m
        JOIN (
            SELECT DISTINCT
                gcm_mi_join_key, site_code, factory_code,
                product_number, target_yield, target_test_time_sec
            FROM gold_gcm_base
        ) g ON m.gcm_mi_join_key = g.gcm_mi_join_key
           AND m.month_key <= 202606
    """)
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gold_cap_act_month
        ON gold_cap_actual (month_key)
    """)
    count = duck_conn.execute(
        "SELECT COUNT(*) FROM gold_cap_actual"
    ).fetchone()[0]
    logger.info(f"    gold_cap_actual: {count:,} rows")
    return count


def build_ml_feature_store(duck_conn) -> int:
    logger.info("  Building gold_ml_feature_store")
    duck_conn.execute("DROP TABLE IF EXISTS gold_ml_feature_store")
    duck_conn.execute("""
        CREATE TABLE gold_ml_feature_store AS
        WITH base AS (
            SELECT
                g.site_code,
                g.product_number,
                g.product_family,
                g.platform,
                g.product_status,
                g.test_type,
                g.month_key,
                g.snapshot_id,
                g.effective_demand_qty      AS demand_qty,
                g.target_yield,
                g.target_test_time_sec,
                g.equip_qty_available,
                g.utilization_rate,
                g.region,
                g.supplier_name,
                -- Calendar features
                (g.month_key % 100)         AS month_of_year,
                CASE
                    WHEN (g.month_key % 100) <= 3  THEN 1
                    WHEN (g.month_key % 100) <= 6  THEN 2
                    WHEN (g.month_key % 100) <= 9  THEN 3
                    ELSE 4
                END                         AS quarter,
                (g.month_key // 100)        AS year,
                CASE
                    WHEN (g.month_key % 100) IN (3, 6, 9, 12) THEN 1
                    ELSE 0
                END                         AS is_quarter_end,
                CASE
                    WHEN g.month_key <= 202606 THEN 1
                    ELSE 0
                END                         AS is_actual
            FROM gold_gcm_base g
            WHERE g.snapshot_id = 'snap-2024-01-planning-cycle'
        ),
        with_lags AS (
            SELECT
                *,
                -- Demand lags
                LAG(demand_qty, 1)  OVER w AS demand_lag_1,
                LAG(demand_qty, 3)  OVER w AS demand_lag_3,
                LAG(demand_qty, 6)  OVER w AS demand_lag_6,
                LAG(demand_qty, 12) OVER w AS demand_lag_12,
                -- Demand rolling averages
                AVG(demand_qty) OVER (
                    PARTITION BY site_code, product_number, test_type
                    ORDER BY month_key
                    ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                )                          AS demand_roll_avg_3,
                AVG(demand_qty) OVER (
                    PARTITION BY site_code, product_number, test_type
                    ORDER BY month_key
                    ROWS BETWEEN 5 PRECEDING AND CURRENT ROW
                )                          AS demand_roll_avg_6,
                STDDEV(demand_qty) OVER (
                    PARTITION BY site_code, product_number, test_type
                    ORDER BY month_key
                    ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                )                          AS demand_roll_std_3,
                -- Yield lags
                LAG(target_yield, 1) OVER w AS yield_lag_1,
                LAG(target_yield, 3) OVER w AS yield_lag_3,
                AVG(target_yield) OVER (
                    PARTITION BY site_code, product_number, test_type
                    ORDER BY month_key
                    ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                )                          AS yield_roll_avg_3,
                -- Test time lags
                LAG(target_test_time_sec, 1) OVER w AS test_time_lag_1,
                AVG(target_test_time_sec) OVER (
                    PARTITION BY site_code, product_number, test_type
                    ORDER BY month_key
                    ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                )                          AS test_time_roll_avg_3
            FROM base
            WINDOW w AS (
                PARTITION BY site_code, product_number, test_type
                ORDER BY month_key
            )
        )
        SELECT
            md5(
                site_code || '|' || product_number || '|' ||
                test_type || '|' || CAST(month_key AS VARCHAR)
            )                           AS feat_pk,
            *
        FROM with_lags
    """)
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gold_feat_month
        ON gold_ml_feature_store (month_key)
    """)
    count = duck_conn.execute(
        "SELECT COUNT(*) FROM gold_ml_feature_store"
    ).fetchone()[0]
    logger.info(f"    gold_ml_feature_store: {count:,} rows")
    return count