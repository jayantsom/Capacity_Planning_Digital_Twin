"""
CapEx Agent tools
Queries: gold_capex_mc_summary, gold_capex_mc_scenarios
"""

from agentic.mcp_server.db import query


def get_capex_recommendation(
    site_code: str | None = None,
    test_type: str | None = None,
    limit: int = 100,
) -> dict:
    """
    Return P50/P80/P95 Monte Carlo equipment recommendations and USD CapEx.

    Args:
        site_code: Filter to specific site. None = all sites.
        test_type: Filter to specific test type. None = all types.
        limit: Max rows.

    Returns:
        {"columns": [...], "rows": [...], "row_count": N, "total_capex_p80_usd": N}
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
            test_type,
            current_equipment_qty,
            eq_needed_p50,
            eq_needed_p80,
            eq_needed_p95,
            delta_units_p80,
            capex_usd_p80,
            equipment_unit_cost_usd,
            demand_mean,
            n_simulations
        FROM gold_capex_mc_summary
        {where}
        ORDER BY capex_usd_p80 DESC
        LIMIT {min(int(limit), 500)}
    """
    try:
        rows = query(sql, params)
        total_capex = sum(r["capex_usd_p80"] for r in rows
                         if r["capex_usd_p80"] is not None)
        return {
            "columns": list(rows[0].keys()) if rows else [],
            "rows": rows,
            "row_count": len(rows),
            "total_capex_p80_usd": int(total_capex),
        }
    except Exception as e:
        return {"error": str(e)}


def get_capex_scenarios(
    site_code: str | None = None,
    test_type: str | None = None,
    limit: int = 200,
) -> dict:
    """
    Return underinvest / target / overinvest scenario comparison per site × test_type.
    Useful for showing the cost-risk tradeoff in planning decisions.

    Args:
        site_code: Filter to specific site. None = all.
        test_type: Filter to specific test type. None = all.
        limit: Max rows.

    Returns:
        {"columns": [...], "rows": [...], "row_count": N}
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
            test_type,
            scenario,
            equipment_qty,
            probability_sufficient,
            capex_usd
        FROM gold_capex_mc_scenarios
        {where}
        ORDER BY site_code, test_type,
                 CASE scenario
                     WHEN 'underinvest_p50' THEN 1
                     WHEN 'target_p80'      THEN 2
                     WHEN 'overinvest_p95'  THEN 3
                 END
        LIMIT {min(int(limit), 1000)}
    """
    try:
        rows = query(sql, params)
        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}
