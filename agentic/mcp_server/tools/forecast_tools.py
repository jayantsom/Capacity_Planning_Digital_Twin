"""
Forecast Agent tools
Queries: gold_demand_forecast, gold_forecast_accuracy_ml
"""

from agentic.mcp_server.db import query


def get_demand_forecast(
    product_number: str | None = None,
    site_code: str | None = None,
    month_from: int | None = None,
    month_to: int | None = None,
    forecast_method: str | None = None,
    limit: int = 200,
) -> dict:
    """
    Return 18-month demand forecast per product × site.

    Args:
        product_number:   Filter to specific product.
        site_code:        Filter to specific site.
        month_from / month_to: Forecast month range as yyyymm integers.
        forecast_method:  One of 'ensemble' or 'croston'. None = all.
        limit: Max rows.

    Returns:
        {"columns": [...], "rows": [...], "row_count": N}
    """
    filters, params = [], []
    if product_number:
        filters.append("product_id = ?"); params.append(product_number)
    if site_code:
        filters.append("site_id = ?"); params.append(site_code)
    if month_from:
        filters.append("forecast_month_key >= ?"); params.append(int(month_from))
    if month_to:
        filters.append("forecast_month_key <= ?"); params.append(int(month_to))
    if forecast_method:
        filters.append("forecast_method = ?"); params.append(forecast_method.lower())

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        SELECT
            product_id          AS product_number,
            site_id             AS site_code,
            forecast_month_key,
            forecast_horizon_months,
            demand_forecast,
            forecast_method
        FROM gold_demand_forecast
        {where}
        ORDER BY forecast_month_key, product_id, site_id
        LIMIT {min(int(limit), 2000)}
    """
    try:
        rows = query(sql, params)
        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}


def get_forecast_accuracy(
    product_number: str | None = None,
    site_code: str | None = None,
    limit: int = 100,
) -> dict:
    """
    Return backtested forecast accuracy metrics (MAPE, SMAPE, RMSE, MAE)
    per product × site.

    Args:
        product_number: Filter to specific product. None = all.
        site_code:      Filter to specific site. None = all.
        limit: Max rows.

    Returns:
        {"columns": [...], "rows": [...], "row_count": N}
    """
    filters, params = [], []
    if product_number:
        filters.append("product_id = ?"); params.append(product_number)
    if site_code:
        filters.append("site_id = ?"); params.append(site_code)

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        SELECT
            product_id      AS product_number,
            site_id         AS site_code,
            backtest_months,
            mape_pct,
            smape_pct,
            rmse,
            mae
        FROM gold_forecast_accuracy_ml
        {where}
        ORDER BY mape_pct ASC
        LIMIT {min(int(limit), 1000)}
    """
    try:
        rows = query(sql, params)

        # Append aggregate summary
        if rows:
            mapes = [r["mape_pct"] for r in rows if r["mape_pct"] is not None]
            summary = {
                "median_mape_pct": round(sorted(mapes)[len(mapes) // 2], 2) if mapes else None,
                "mean_mape_pct":   round(sum(mapes) / len(mapes), 2) if mapes else None,
                "total_series":    len(rows),
            }
        else:
            summary = {}

        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows), "summary": summary}
    except Exception as e:
        return {"error": str(e)}
