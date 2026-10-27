"""Tools for truthful weekly and monthly execution analytics."""

from typing import Literal

from operations_assistant.agentic.mcp_server.db import query


def get_operational_performance(
    grain: Literal["WEEK", "MONTH"] = "MONTH",
    site_code: str | None = None,
    test_type: str | None = None,
    month_from: int | None = None,
    month_to: int | None = None,
    limit: int = 100,
) -> dict:
    """Return recomputed operational yield, OEE, downtime, and throughput."""
    filters = ["period_grain = ?"]
    params: list = [grain]
    if site_code:
        filters.append("site_code = ?")
        params.append(site_code)
    if test_type:
        filters.append("test_type = ?")
        params.append(test_type)
    if month_from:
        filters.append(
            "CAST(strftime(period_end, '%Y%m') AS INTEGER) >= ?"
        )
        params.append(int(month_from))
    if month_to:
        filters.append(
            "CAST(strftime(period_start, '%Y%m') AS INTEGER) <= ?"
        )
        params.append(int(month_to))
    where = " AND ".join(filters)
    sql = f"""
        WITH aggregate AS (
            SELECT
                period_key,
                MIN(period_start) AS period_start,
                MAX(period_end) AS period_end,
                BOOL_AND(period_complete) AS period_complete,
                SUM(passed_qty) AS passed_qty,
                SUM(tested_qty) AS tested_qty,
                SUM(observation_rows) AS observation_rows,
                SUM(downtime_seconds) AS downtime_seconds,
                SUM(productive_seconds) AS productive_seconds
            FROM srv_vw_operational_performance
            WHERE {where}
            GROUP BY period_key
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
                ) AS availability,
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
                ) AS performance,
                LEAST(1.0, GREATEST(0.0, passed_qty / NULLIF(tested_qty, 0)))
                    AS quality
            FROM aggregate
        )
        SELECT
            period_key,
            period_start,
            period_end,
            period_complete,
            quality AS yield_pct,
            availability * performance * quality AS oee_pct,
            downtime_seconds / 3600.0 AS downtime_hours,
            tested_qty
                / NULLIF(
                    (observation_rows * 8.0 * 3600.0 - downtime_seconds) / 3600.0,
                    0
                ) AS throughput_uph
        FROM rates
        ORDER BY period_key
        LIMIT {min(int(limit), 500)}
    """
    try:
        rows = query(sql, params)
        return {
            "native_grain": "DAY",
            "grain": grain,
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows,
            "row_count": len(rows),
        }
    except Exception:
        return {"error": "Operational performance data is unavailable."}
