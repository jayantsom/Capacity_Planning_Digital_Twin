"""
Maintenance Agent tools
Queries: gold_maintenance_risk, gold_maintenance_alerts
"""

from operations_assistant.agentic.mcp_server.db import query


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
        filters.append("alert.site_id = ?"); params.append(site_code)
    if test_type:
        filters.append("alert.test_type_id = ?"); params.append(test_type.upper())
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
            site.site_name,
            test_type_id    AS test_type,
            test.test_category_name AS test_type_name,
            month,
            risk_tier,
            failure_prob    AS failure_probability,
            avg_oee,
            alert_generated_at
        FROM gold_maintenance_alerts AS alert
        LEFT JOIN slvr_ref_site AS site
          ON alert.site_id = site.site_code
        LEFT JOIN slvr_ref_test_type AS test
          ON alert.test_type_id = test.test_type
        {where}
        ORDER BY failure_prob DESC, month
        LIMIT {min(int(limit), 2000)}
    """
    try:
        rows = query(sql, params, database="ml")
        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception:
        return {"error": "Maintenance alert data is unavailable."}


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
        filters.append("risk.site_id = ?"); params.append(site_code)
    if test_type:
        filters.append("risk.test_type_id = ?"); params.append(test_type.upper())
    if month_from:
        filters.append("month >= ?"); params.append(int(month_from))
    if month_to:
        filters.append("month <= ?"); params.append(int(month_to))

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        SELECT
            site_id         AS site_code,
            site.site_name,
            test_type_id    AS test_type,
            test.test_category_name AS test_type_name,
            risk.equipment_id,
            equipment.equipment_name,
            month,
            failure_prob    AS failure_probability,
            risk_tier,
            avg_oee,
            failure_label   AS actual_failure_occurred
        FROM gold_maintenance_risk AS risk
        LEFT JOIN slvr_ref_site AS site
          ON risk.site_id = site.site_code
        LEFT JOIN slvr_ref_test_type AS test
          ON risk.test_type_id = test.test_type
        LEFT JOIN slvr_ref_equipment AS equipment
          ON risk.equipment_id = equipment.equipment_id
        {where}
        ORDER BY month, site_id, test_type_id
        LIMIT {min(int(limit), 2000)}
    """
    try:
        rows = query(sql, params, database="ml")
        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception:
        return {"error": "Maintenance risk data is unavailable."}
