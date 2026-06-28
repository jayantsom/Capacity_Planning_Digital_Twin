"""
Maintenance Agent tools
Queries: gold_maintenance_risk, gold_maintenance_alerts
"""

from agentic.mcp_server.db import query


def get_maintenance_alerts(
    site_code: str | None = None,
    test_type: str | None = None,
    risk_tier: str | None = None,
    month_from: int | None = None,
    month_to: int | None = None,
    limit: int = 200,
) -> dict:
    """
    Return HIGH / CRITICAL maintenance alerts for equipment.

    Args:
        site_code:  Filter to specific site.
        test_type:  Filter to specific test type.
        risk_tier:  One of HIGH / CRITICAL. None = both.
        month_from / month_to: Month range as yyyymm integers.
        limit: Max rows.

    Returns:
        {"columns": [...], "rows": [...], "row_count": N}
    """
    filters, params = [], []
    if site_code:
        filters.append("site_id = ?"); params.append(site_code)
    if test_type:
        filters.append("test_type_id = ?"); params.append(test_type.upper())
    if risk_tier:
        filters.append("risk_tier = ?"); params.append(risk_tier.upper())
    if month_from:
        filters.append("month >= ?"); params.append(int(month_from))
    if month_to:
        filters.append("month <= ?"); params.append(int(month_to))

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        SELECT
            site_id         AS site_code,
            test_type_id    AS test_type,
            month,
            risk_tier,
            failure_prob    AS failure_probability,
            avg_oee,
            alert_generated_at
        FROM gold_maintenance_alerts
        {where}
        ORDER BY failure_prob DESC, month
        LIMIT {min(int(limit), 2000)}
    """
    try:
        rows = query(sql, params)
        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}


def get_failure_risk_trend(
    site_code: str | None = None,
    test_type: str | None = None,
    month_from: int | None = None,
    month_to: int | None = None,
    limit: int = 200,
) -> dict:
    """
    Return failure probability trend over time for a site × test_type.
    Shows how risk evolves month by month — useful for planning maintenance windows.

    Args:
        site_code:  Filter to specific site.
        test_type:  Filter to specific test type.
        month_from / month_to: Month range as yyyymm integers.
        limit: Max rows.

    Returns:
        {"columns": [...], "rows": [...], "row_count": N}
    """
    filters, params = [], []
    if site_code:
        filters.append("site_id = ?"); params.append(site_code)
    if test_type:
        filters.append("test_type_id = ?"); params.append(test_type.upper())
    if month_from:
        filters.append("month >= ?"); params.append(int(month_from))
    if month_to:
        filters.append("month <= ?"); params.append(int(month_to))

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        SELECT
            site_id         AS site_code,
            test_type_id    AS test_type,
            month,
            failure_prob    AS failure_probability,
            risk_tier,
            avg_oee,
            failure_label   AS actual_failure_occurred
        FROM gold_maintenance_risk
        {where}
        ORDER BY month, site_id, test_type_id
        LIMIT {min(int(limit), 2000)}
    """
    try:
        rows = query(sql, params)
        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}
