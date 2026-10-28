"""
Gold layer: Analytics tables.
Built from gold_gcm_base and gold_cap_* using DuckDB SQL.
DuckDB is faster than Spark for these aggregation patterns.
"""

from capacity_twin_core.capacity.formulas import calculate_oee
from capacity_twin_core.logging import logger
from capacity_twin_core.planning import latest_planning_version_predicate
from data_operations.pipeline.pipeline.gold.utils import write_gold_table


def build_demand_vs_capacity(duck_conn) -> int:
    logger.info("  Building gold_dmnd_vs_cap")
    duck_conn.execute("DROP TABLE IF EXISTS gold_dmnd_vs_cap")
    duck_conn.execute("""
        CREATE TABLE gold_dmnd_vs_cap AS
        WITH capacity_data AS (
            SELECT * FROM gold_cap_normal
            UNION ALL BY NAME
            SELECT * FROM gold_cap_maximum
        )
        SELECT
            md5(
                capacity.site_code || '|' || capacity.product_number || '|' ||
                capacity.test_type  || '|' || capacity.equipment_id  || '|' ||
                CAST(capacity.month_key AS VARCHAR) || '|' ||
                capacity.planning_version_id || '|' ||
                capacity.capacity_mode || '|' || capacity.retest_type
            )                           AS gap_pk,
            capacity.gcm_pk,
            capacity.site_code,
            capacity.factory_code,
            capacity.month_key,
            capacity.planning_version_id,
            capacity.plan_as_of_date,
            capacity.product_number,
            capacity.product_family,
            capacity.platform,
            capacity.test_type,
            capacity.equipment_id,
            capacity.equipment_type,
            capacity.capacity_mode,
            capacity.retest_type,
            capacity.effective_demand_qty AS demand_qty,
            capacity.capacity_qty,
            capacity.gap_qty,
            capacity.gap_pct,
            capacity.utilization_pct,
            capacity.is_bottleneck,
            capacity.is_excess,
            capacity.excess_capacity_units,
            capacity.investment_need_units,
            capacity.bottleneck_severity,
            -- Flexibility: how much surge normal→max provides
            CASE
                WHEN normal.capacity_qty > 0 AND maximum.capacity_qty > 0
                THEN (maximum.capacity_qty - normal.capacity_qty)
                    / normal.capacity_qty
                ELSE NULL
            END                         AS flexibility_pct
        FROM capacity_data capacity
        LEFT JOIN gold_cap_normal normal
            ON capacity.gcm_pk = normal.gcm_pk
           AND capacity.retest_type = normal.retest_type
        LEFT JOIN gold_cap_maximum maximum
            ON capacity.gcm_pk = maximum.gcm_pk
           AND capacity.retest_type = maximum.retest_type
    """)
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gold_dvc_month
        ON gold_dmnd_vs_cap (month_key)
    """)
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gold_dvc_site
        ON gold_dmnd_vs_cap (site_code)
    """)
    count = duck_conn.execute("SELECT COUNT(*) FROM gold_dmnd_vs_cap").fetchone()[0]
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
                planning_version_id || '|' || capacity_mode || '|' || retest_type
            )                               AS bottleneck_pk,
            site_code,
            month_key,
            planning_version_id,
            plan_as_of_date,
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
                WHEN MIN(gap_pct) <= 0.05 THEN 'BALANCED'
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
            site_code, month_key, planning_version_id, plan_as_of_date, capacity_mode,
            retest_type, test_type, equipment_type
    """)
    count = duck_conn.execute("SELECT COUNT(*) FROM gold_bottleneck").fetchone()[0]
    logger.info(f"    gold_bottleneck: {count:,} rows")
    return count


def build_oee_metrics(duck_conn) -> int:
    logger.info("  Building gold_oee_metrics")
    metrics = duck_conn.execute(
        """
        SELECT
            md5(
                factory_code || '|' || test_category_id || '|' ||
                CAST(month_key AS VARCHAR)
            ) AS oee_pk,
            factory_code,
            site_code,
            test_category_id,
            test_type,
            month_key,
            LEAST(1.0, GREATEST(0.0,
                COALESCE(1.0 - AVG(equipment_downtime_avg) / (8.0 * 3600), 0.85)
            )) AS availability_pct,
            LEAST(1.0, GREATEST(0.0,
                COALESCE(
                    AVG(actual_throughput) /
                    NULLIF(AVG(actual_throughput) + AVG(idle_time_avg) / 60.0, 0),
                    0.85
                )
            )) AS performance_pct,
            LEAST(1.0, GREATEST(0.0, COALESCE(AVG(yield_avg), 0.85)))
                AS quality_pct,
            AVG(actual_throughput) AS actual_throughput,
            SUM(passed_qty_sum) AS total_passed,
            SUM(total_qty_sum) AS total_produced,
            AVG(equipment_downtime_avg) / 3600.0 AS avg_downtime_hr
        FROM slvr_machine_execution
        WHERE yield_avg IS NOT NULL AND is_valid
        GROUP BY
            factory_code, site_code, test_category_id, test_type, month_key
        """
    ).df()
    metrics["oee_pct"] = metrics.apply(
        lambda row: calculate_oee(
            row["availability_pct"], row["performance_pct"], row["quality_pct"]
        ),
        axis=1,
    )
    for column in ("availability_pct", "performance_pct", "quality_pct", "oee_pct"):
        metrics[column] = metrics[column].round(4)
    count = write_gold_table(metrics, "gold_oee_metrics", duck_conn, indexes=["month_key"])
    logger.info(f"    gold_oee_metrics: {count:,} rows")
    return count


def build_operational_time_grains(duck_conn) -> dict[str, int]:
    """Publish honest weekly/monthly rollups from daily and event facts."""
    logger.info("  Building gold_operational_performance")
    duck_conn.execute("DROP TABLE IF EXISTS gold_operational_performance")
    duck_conn.execute(
        """
        CREATE TABLE gold_operational_performance AS
        WITH parameter_source AS (
            SELECT
                factory_code,
                site_code,
                product_number,
                test_type,
                CAST(execution_date AS DATE) AS execution_date,
                SUM(first_pass_qty_sum) AS first_pass_qty_sum,
                SUM(first_fail_qty_sum) AS first_fail_qty_sum
            FROM slvr_machine_test_param
            WHERE is_valid
            GROUP BY ALL
        ),
        source AS (
            SELECT
                execution.factory_code,
                execution.site_code,
                execution.product_number,
                execution.test_type,
                CAST(execution.execution_date AS DATE) AS execution_date,
                execution.passed_qty_sum,
                execution.failed_qty_sum,
                execution.total_qty_sum,
                parameters.first_pass_qty_sum,
                parameters.first_fail_qty_sum,
                execution.test_duration_avg,
                execution.handling_time_avg,
                execution.idle_time_avg,
                execution.equipment_downtime_avg,
                execution.actual_throughput,
                execution.pipeline_run_id
            FROM slvr_machine_execution AS execution
            LEFT JOIN parameter_source AS parameters
              ON execution.factory_code = parameters.factory_code
             AND execution.site_code = parameters.site_code
             AND execution.product_number = parameters.product_number
             AND execution.test_type = parameters.test_type
             AND CAST(execution.execution_date AS DATE) = parameters.execution_date
            WHERE execution.is_valid
        ),
        bounds AS (
            SELECT MIN(execution_date) AS min_date, MAX(execution_date) AS max_date
            FROM source
        ),
        periods AS (
            SELECT
                'WEEK' AS period_grain,
                strftime(execution_date, '%G-W%V') AS period_key,
                CAST(date_trunc('week', execution_date) AS DATE) AS period_start,
                CAST(date_trunc('week', execution_date) + INTERVAL 6 DAY AS DATE)
                    AS period_end,
                execution_date,
                * EXCLUDE (execution_date)
            FROM source
            UNION ALL
            SELECT
                'MONTH' AS period_grain,
                strftime(execution_date, '%Y-%m') AS period_key,
                CAST(date_trunc('month', execution_date) AS DATE) AS period_start,
                CAST(last_day(execution_date) AS DATE) AS period_end,
                execution_date,
                * EXCLUDE (execution_date)
            FROM source
        ),
        aggregated AS (
            SELECT
                period_grain,
                period_key,
                period_start,
                period_end,
                factory_code,
                site_code,
                product_number,
                test_type,
                COUNT(DISTINCT execution_date) AS days_present,
                COUNT(*) AS observation_rows,
                SUM(passed_qty_sum) AS passed_qty,
                SUM(failed_qty_sum) AS failed_qty,
                SUM(total_qty_sum) AS tested_qty,
                SUM(first_pass_qty_sum) AS first_pass_qty,
                SUM(first_fail_qty_sum) AS first_fail_qty,
                SUM(equipment_downtime_avg) AS downtime_seconds,
                SUM((test_duration_avg + handling_time_avg) * total_qty_sum)
                    AS productive_seconds,
                SUM(test_duration_avg * total_qty_sum)
                    / NULLIF(SUM(total_qty_sum), 0) AS weighted_test_time_sec,
                SUM(handling_time_avg * total_qty_sum)
                    / NULLIF(SUM(total_qty_sum), 0) AS weighted_handling_time_sec,
                SUM(actual_throughput * total_qty_sum)
                    / NULLIF(SUM(total_qty_sum), 0) AS weighted_throughput_uph,
                SUM(idle_time_avg * total_qty_sum)
                    / NULLIF(SUM(total_qty_sum), 0) AS weighted_idle_time_sec,
                MAX(pipeline_run_id) AS pipeline_run_id
            FROM periods
            GROUP BY ALL
        ),
        rates AS (
            SELECT
                *,
                LEAST(
                    1.0,
                    GREATEST(
                        0.0,
                        1.0 - downtime_seconds
                            / NULLIF(observation_rows * 8.0 * 3600.0, 0)
                    )
                ) AS availability_pct,
                LEAST(
                    1.0,
                    GREATEST(
                        0.0,
                        productive_seconds
                            / NULLIF(
                                observation_rows * 8.0 * 3600.0 - downtime_seconds,
                                0
                            )
                    )
                ) AS performance_pct,
                LEAST(1.0, GREATEST(0.0, passed_qty / NULLIF(tested_qty, 0)))
                    AS quality_pct
            FROM aggregated
        )
        SELECT
            md5(
                period_grain || '|' || period_key || '|' || factory_code || '|' ||
                site_code || '|' || product_number || '|' || test_type
            ) AS operational_period_pk,
            period_grain,
            period_key,
            period_start,
            period_end,
            factory_code,
            site_code,
            product_number,
            test_type,
            days_present,
            observation_rows,
            (
                SELECT COUNT(*)
                FROM generate_series(
                    CAST(period_start AS TIMESTAMP),
                    CAST(period_end AS TIMESTAMP),
                    INTERVAL 1 DAY
                ) AS calendar(day)
                WHERE isodow(day) BETWEEN 1 AND 5
            ) AS expected_working_days,
            period_start >= bounds.min_date AND period_end <= bounds.max_date
                AS period_complete,
            passed_qty,
            failed_qty,
            tested_qty,
            passed_qty / NULLIF(tested_qty, 0) AS yield_pct,
            first_pass_qty,
            first_fail_qty,
            first_pass_qty / NULLIF(first_pass_qty + first_fail_qty, 0)
                AS first_pass_yield_pct,
            downtime_seconds,
            productive_seconds,
            downtime_seconds / 3600.0 AS downtime_hours,
            weighted_test_time_sec,
            weighted_handling_time_sec,
            weighted_throughput_uph,
            availability_pct,
            performance_pct,
            quality_pct,
            LEAST(1.0, GREATEST(0.0, availability_pct * performance_pct * quality_pct))
                AS oee_pct,
            pipeline_run_id
        FROM rates
        CROSS JOIN bounds
        """
    )
    duck_conn.execute(
        """
        CREATE INDEX idx_gold_operational_period
        ON gold_operational_performance (period_grain, period_key)
        """
    )
    performance_count = duck_conn.execute(
        "SELECT COUNT(*) FROM gold_operational_performance"
    ).fetchone()[0]

    logger.info("  Building gold_operational_events")
    duck_conn.execute("DROP TABLE IF EXISTS gold_operational_events")
    duck_conn.execute(
        """
        CREATE TABLE gold_operational_events AS
        WITH source AS (
            SELECT
                factory_code,
                site_code,
                product_number,
                test_type,
                CAST(execution_date AS DATE) AS execution_date,
                severity,
                error_code,
                pipeline_run_id
            FROM slvr_machine_logs
            WHERE is_valid
        ),
        periods AS (
            SELECT
                'WEEK' AS period_grain,
                strftime(execution_date, '%G-W%V') AS period_key,
                CAST(date_trunc('week', execution_date) AS DATE) AS period_start,
                CAST(date_trunc('week', execution_date) + INTERVAL 6 DAY AS DATE)
                    AS period_end,
                * EXCLUDE (execution_date)
            FROM source
            UNION ALL
            SELECT
                'MONTH' AS period_grain,
                strftime(execution_date, '%Y-%m') AS period_key,
                CAST(date_trunc('month', execution_date) AS DATE) AS period_start,
                CAST(last_day(execution_date) AS DATE) AS period_end,
                * EXCLUDE (execution_date)
            FROM source
        )
        SELECT
            md5(
                period_grain || '|' || period_key || '|' || factory_code || '|' ||
                site_code || '|' || product_number || '|' || test_type || '|' ||
                severity || '|' || error_code
            ) AS operational_event_pk,
            period_grain,
            period_key,
            period_start,
            period_end,
            factory_code,
            site_code,
            product_number,
            test_type,
            severity,
            error_code,
            COUNT(*) AS event_count,
            MAX(pipeline_run_id) AS pipeline_run_id
        FROM periods
        GROUP BY ALL
        """
    )
    event_count = duck_conn.execute(
        "SELECT COUNT(*) FROM gold_operational_events"
    ).fetchone()[0]
    logger.info(
        f"    operational performance: {performance_count:,} rows | "
        f"events: {event_count:,} rows"
    )
    return {
        "gold_operational_performance": performance_count,
        "gold_operational_events": event_count,
    }


def build_forecast_accuracy(duck_conn) -> int:
    logger.info("  Building gold_forecast_accuracy")
    duck_conn.execute("DROP TABLE IF EXISTS gold_forecast_accuracy")
    duck_conn.execute("""
        CREATE TABLE gold_forecast_accuracy AS
        WITH requirements AS (
            SELECT
                site_code,
                product_number,
                month_key,
                planning_version_id,
                plan_as_of_date,
                data_type,
                SUM(total_requirement_qty) AS demand_qty
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
        actuals AS (
            SELECT
                site_code, product_number, month_key,
                demand_qty AS actual_qty
            FROM (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY site_code, product_number, month_key
                        ORDER BY plan_as_of_date DESC, planning_version_id DESC
                    ) AS recency
                FROM requirements
                WHERE data_type = 'ACTUAL'
            )
            WHERE recency = 1
        ),
        forecasts AS (
            SELECT
                site_code, product_number, month_key,
                demand_qty AS forecast_qty,
                planning_version_id, plan_as_of_date,
                'SYNTHETIC_REQUIREMENT' AS forecast_source
            FROM requirements
            WHERE data_type = 'FORECAST'
        )
        SELECT
            md5(
                f.site_code || '|' || f.product_number || '|' ||
                CAST(f.month_key AS VARCHAR) || '|' || f.planning_version_id
            )                               AS fa_pk,
            f.site_code,
            f.product_number,
            f.month_key,
            f.planning_version_id,
            f.plan_as_of_date,
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
    count = duck_conn.execute("SELECT COUNT(*) FROM gold_forecast_accuracy").fetchone()[0]
    logger.info(f"    gold_forecast_accuracy: {count:,} rows")
    return count


def build_actual_capacity(duck_conn) -> int:
    """Publish measured output at execution grain, independent of planning vintages."""
    logger.info("  Building gold_cap_actual")
    duck_conn.execute("DROP TABLE IF EXISTS gold_cap_actual")
    duck_conn.execute("""
        CREATE TABLE gold_cap_actual AS
        SELECT
            md5(
                site_code || '|' || product_number || '|' ||
                test_type || '|' || CAST(month_key AS VARCHAR)
            )                               AS cap_act_pk,
            factory_code || '|' || test_category_id || '|' || product_number
                AS gcm_machine_join_key,
            site_code,
            factory_code,
            month_key,
            product_number,
            test_category_id,
            test_type,
            SUM(passed_qty_sum) AS actual_passed_qty,
            SUM(failed_qty_sum) AS actual_failed_qty,
            SUM(total_qty_sum) AS actual_total_qty,
            SUM(passed_qty_sum) / NULLIF(SUM(total_qty_sum), 0) AS actual_yield_avg,
            AVG(final_test_yield_avg) AS actual_final_yield_avg,
            SUM(test_duration_avg * total_qty_sum) / NULLIF(SUM(total_qty_sum), 0)
                AS actual_test_duration_avg,
            SUM(handling_time_avg * total_qty_sum) / NULLIF(SUM(total_qty_sum), 0)
                AS actual_handling_time_avg,
            SUM(actual_throughput * total_qty_sum) / NULLIF(SUM(total_qty_sum), 0)
                AS actual_throughput_avg,
            SUM(equipment_downtime_avg) AS actual_downtime_seconds,
            'EA' AS output_unit,
            'MEASURED_EXECUTION' AS output_method
        FROM slvr_machine_execution
        WHERE is_valid AND yield_avg IS NOT NULL
        GROUP BY
            factory_code, site_code, product_number,
            test_category_id, test_type, month_key
    """)
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gold_cap_act_month
        ON gold_cap_actual (month_key)
    """)
    count = duck_conn.execute("SELECT COUNT(*) FROM gold_cap_actual").fetchone()[0]
    logger.info(f"    gold_cap_actual: {count:,} rows")
    return count


def build_demonstrated_capacity(duck_conn) -> int:
    """Publish a trailing measured-output capacity without reapplying loss factors."""
    logger.info("  Building gold_demonstrated_capacity")
    duck_conn.execute("DROP TABLE IF EXISTS gold_demonstrated_capacity")
    duck_conn.execute(
        """
        CREATE TABLE gold_demonstrated_capacity AS
        WITH monthly AS (
            SELECT * FROM gold_cap_actual
        ),
        demonstrated AS (
            SELECT
                site_code,
                factory_code,
                product_number,
                test_category_id,
                test_type,
                month_key,
                MIN(month_key) OVER window_3 AS observation_start_month,
                MAX(month_key) OVER window_3 AS observation_end_month,
                COUNT(*) OVER window_3 AS observation_months,
                AVG(actual_passed_qty) OVER window_3 AS demonstrated_capacity_qty,
                SUM(actual_passed_qty) OVER window_3 AS observed_passed_qty,
                SUM(actual_total_qty) OVER window_3 AS observed_tested_qty
            FROM monthly
            WINDOW window_3 AS (
                PARTITION BY site_code, product_number, test_type
                ORDER BY month_key
                ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
            )
        )
        SELECT
            md5(
                site_code || '|' || product_number || '|' || test_type || '|' ||
                CAST(month_key AS VARCHAR)
            ) AS demonstrated_capacity_pk,
            *,
            'EA_PER_MONTH' AS capacity_unit,
            'TRAILING_3_MONTH_MEAN_ACTUAL_OUTPUT' AS formula_id,
            CASE WHEN observation_months < 3
                 THEN 'AVAILABLE_HISTORY_MEAN'
                 ELSE 'NONE' END AS fallback_policy,
            true AS excludes_future_actuals,
            true AS loss_factors_not_reapplied
        FROM demonstrated
        """
    )
    count = int(
        duck_conn.execute("SELECT COUNT(*) FROM gold_demonstrated_capacity").fetchone()[0]
    )
    logger.info(f"    gold_demonstrated_capacity: {count:,} rows")
    return count


def build_ml_feature_store(duck_conn) -> int:
    logger.info("  Building gold_ml_feature_store")
    latest_version = latest_planning_version_predicate(
        "gold_gcm_base", row_alias="candidate"
    )
    latest_version_aliased = latest_planning_version_predicate(
        "gold_gcm_base", row_alias="g"
    )
    conflicts = duck_conn.execute(
        f"""
        SELECT COUNT(*)
        FROM (
            SELECT
                site_code, product_number, test_type, month_key, planning_version_id
            FROM gold_gcm_base AS candidate
            WHERE {latest_version}
            GROUP BY
                site_code, product_number, test_type, month_key, planning_version_id
            HAVING
                COUNT(DISTINCT effective_demand_qty) > 1
                OR COUNT(DISTINCT target_yield) > 1
                OR COUNT(DISTINCT target_test_time_sec) > 1
        )
        """
    ).fetchone()[0]
    if conflicts:
        raise ValueError(
            f"Cannot build ML feature store: {conflicts} business keys have conflicting values"
        )

    duck_conn.execute("DROP TABLE IF EXISTS gold_ml_feature_store")
    duck_conn.execute(f"""
        CREATE TABLE gold_ml_feature_store AS
        WITH resource_rows AS (
            SELECT
                g.site_code,
                g.product_number,
                g.product_family,
                g.platform,
                g.test_type,
                g.month_key,
                g.planning_version_id,
                g.route_step_demand_qty     AS demand_qty,
                g.target_yield,
                g.target_test_time_sec,
                g.region,
                g.equipment_id,
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
                    WHEN g.data_type = 'ACTUAL' THEN 1
                    ELSE 0
                END                         AS is_actual
            FROM gold_gcm_base g
            WHERE {latest_version_aliased}
        ),
        base AS (
            SELECT
                site_code,
                product_number,
                MAX(product_family) AS product_family,
                MAX(platform) AS platform,
                test_type,
                month_key,
                planning_version_id,
                MAX(demand_qty) AS demand_qty,
                MAX(target_yield) AS target_yield,
                MAX(target_test_time_sec) AS target_test_time_sec,
                MAX(region) AS region,
                COUNT(DISTINCT equipment_id) AS qualified_resource_count,
                MAX(month_of_year) AS month_of_year,
                MAX(quarter) AS quarter,
                MAX(year) AS year,
                MAX(is_quarter_end) AS is_quarter_end,
                MAX(is_actual) AS is_actual
            FROM resource_rows
            GROUP BY
                site_code, product_number, test_type, month_key, planning_version_id
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
                    ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
                )                          AS demand_roll_avg_3,
                AVG(demand_qty) OVER (
                    PARTITION BY site_code, product_number, test_type
                    ORDER BY month_key
                    ROWS BETWEEN 6 PRECEDING AND 1 PRECEDING
                )                          AS demand_roll_avg_6,
                STDDEV(demand_qty) OVER (
                    PARTITION BY site_code, product_number, test_type
                    ORDER BY month_key
                    ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
                )                          AS demand_roll_std_3,
                -- Yield lags
                LAG(target_yield, 1) OVER w AS yield_lag_1,
                LAG(target_yield, 3) OVER w AS yield_lag_3,
                AVG(target_yield) OVER (
                    PARTITION BY site_code, product_number, test_type
                    ORDER BY month_key
                    ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
                )                          AS yield_roll_avg_3,
                -- Test time lags
                LAG(target_test_time_sec, 1) OVER w AS test_time_lag_1,
                AVG(target_test_time_sec) OVER (
                    PARTITION BY site_code, product_number, test_type
                    ORDER BY month_key
                    ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING
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
                test_type || '|' || CAST(month_key AS VARCHAR) || '|' ||
                planning_version_id
            )                           AS feat_pk,
            *
        FROM with_lags
    """)
    duck_conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_gold_feat_month
        ON gold_ml_feature_store (month_key)
    """)
    count = duck_conn.execute("SELECT COUNT(*) FROM gold_ml_feature_store").fetchone()[0]
    logger.info(f"    gold_ml_feature_store: {count:,} rows")
    return count
