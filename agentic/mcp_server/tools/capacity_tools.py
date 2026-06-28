"""
Capacity Agent tools
Queries: gold_cap_normal, gold_bottleneck, gold_dmnd_vs_cap,
         srv_vw_equipment_utilization
"""

from agentic.mcp_server.db import query


def get_capacity_summary(
    site_code: str | None = None,
    month_from: int | None = None,
    month_to: int | None = None,
    limit: int = 100,
) -> dict:
    """
    Return capacity summary: utilization %, supply, demand, gap % per
    site × test_type × month.

    Args:
        site_code:  Filter to a specific site (e.g. 'SG01'). None = all.
        month_from: Start month yyyymm (e.g. 202301). None = all.
        month_to:   End month yyyymm (e.g. 202312). None = all.
        limit:      Max rows (default 100).
    """
    filters, params = [], []
    if site_code:
        filters.append("site_code = ?"); params.append(site_code)
    if month_from:
        filters.append("month_key >= ?"); params.append(int(month_from))
    if month_to:
        filters.append("month_key <= ?"); params.append(int(month_to))

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        SELECT
            site_code,
            test_type,
            month_key,
            capacity_mode,
            SUM(capacity_qty)           AS total_supply,
            SUM(effective_demand_qty)   AS total_demand,
            AVG(utilization_pct)        AS avg_utilization_pct,
            AVG(gap_pct)                AS avg_gap_pct,
            SUM(investment_need_units)  AS total_investment_need_units,
            SUM(excess_capacity_units)  AS total_excess_units
        FROM gold_cap_normal
        {where}
        GROUP BY site_code, test_type, month_key, capacity_mode
        ORDER BY month_key, site_code, test_type
        LIMIT {min(int(limit), 1000)}
    """
    try:
        rows = query(sql, params)
        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}


def get_bottleneck_analysis(
    site_code: str | None = None,
    severity: str | None = None,
    month_from: int | None = None,
    month_to: int | None = None,
    limit: int = 100,
) -> dict:
    """
    Return bottleneck analysis per site × test_type.

    Args:
        site_code: Filter to specific site. None = all.
        severity:  CRITICAL / HIGH / MEDIUM / LOW / BALANCED / EXCESS.
        month_from / month_to: Month range as yyyymm integers.
        limit: Max rows.
    """
    filters, params = [], []
    if site_code:
        filters.append("site_code = ?"); params.append(site_code)
    if severity:
        filters.append("bottleneck_severity = ?"); params.append(severity.upper())
    if month_from:
        filters.append("month_key >= ?"); params.append(int(month_from))
    if month_to:
        filters.append("month_key <= ?"); params.append(int(month_to))

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        SELECT
            site_code,
            test_type,
            month_key,
            capacity_mode,
            bottleneck_severity,
            avg_gap_pct,
            min_gap_pct,
            avg_utilization_pct,
            affected_products,
            affected_demand_qty,
            total_investment_need_units,
            worst_gap_qty
        FROM gold_bottleneck
        {where}
        ORDER BY avg_gap_pct ASC, month_key
        LIMIT {min(int(limit), 1000)}
    """
    try:
        rows = query(sql, params)
        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}


def get_demand_vs_supply(
    product_number: str | None = None,
    site_code: str | None = None,
    month_from: int | None = None,
    month_to: int | None = None,
    limit: int = 200,
) -> dict:
    """
    Return demand vs supply comparison over time per product × site.

    Args:
        product_number: Filter to specific product. None = all.
        site_code:      Filter to specific site. None = all.
        month_from / month_to: Month range as yyyymm integers.
        limit: Max rows.
    """
    filters, params = [], []
    if product_number:
        filters.append("product_number = ?"); params.append(product_number)
    if site_code:
        filters.append("site_code = ?"); params.append(site_code)
    if month_from:
        filters.append("month_key >= ?"); params.append(int(month_from))
    if month_to:
        filters.append("month_key <= ?"); params.append(int(month_to))

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        SELECT
            product_number,
            site_code,
            test_type,
            month_key,
            capacity_mode,
            demand_qty,
            capacity_qty,
            gap_qty,
            gap_pct,
            utilization_pct,
            bottleneck_severity,
            investment_need_units,
            excess_capacity_units
        FROM gold_dmnd_vs_cap
        {where}
        ORDER BY month_key, site_code, product_number
        LIMIT {min(int(limit), 2000)}
    """
    try:
        rows = query(sql, params)
        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}


def get_equipment_utilization(
    site_code: str | None = None,
    test_type: str | None = None,
    limit: int = 100,
) -> dict:
    """
    Return equipment utilization summary from the serving view.

    Args:
        site_code: Filter to specific site.
        test_type: Filter to specific test type (OTA/TRX/PIM/PAM/FCT/ICT/BIT/ALT/UC/AT).
        limit: Max rows.
    """
    filters, params = [], []
    if site_code:
        filters.append("site_code = ?"); params.append(site_code)
    if test_type:
        filters.append("test_type = ?"); params.append(test_type.upper())

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        SELECT
            site_code,
            region,
            month_key,
            test_type,
            equipment_id,
            equipment_type,
            capacity_mode,
            avg_utilization_pct,
            max_utilization_pct,
            min_capacity_qty,
            total_demand_qty,
            total_investment_need
        FROM srv_vw_equipment_utilization
        {where}
        ORDER BY avg_utilization_pct DESC
        LIMIT {min(int(limit), 500)}
    """
    try:
        rows = query(sql, params)
        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}
