"""
Yield Agent tools
Queries: gold_yield_predictions, gold_yield_shap, gold_cap_ml_adjusted
"""

from agentic.mcp_server.db import query


def get_yield_prediction(
    site_code: str | None = None,
    test_type: str | None = None,
    product_number: str | None = None,
    month_from: int | None = None,
    month_to: int | None = None,
    limit: int = 200,
) -> dict:
    """
    Return ML-predicted yield vs actual yield per site × test_type × product × month.

    Args:
        site_code:      Filter to specific site (e.g. 'SG01').
        test_type:      Filter to specific test type (e.g. 'OTA').
        product_number: Filter to specific product.
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
    if product_number:
        filters.append("product_id = ?"); params.append(product_number)
    if month_from:
        filters.append("month >= ?"); params.append(int(month_from))
    if month_to:
        filters.append("month <= ?"); params.append(int(month_to))

    where = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        SELECT
            site_id         AS site_code,
            test_type_id    AS test_type,
            product_id      AS product_number,
            month,
            avg_yield       AS actual_yield,
            predicted_yield,
            abs_error_pp    AS error_percentage_points
        FROM gold_yield_predictions
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


def get_yield_drivers(
    site_code: str | None = None,
    test_type: str | None = None,
    top_n: int = 10,
) -> dict:
    """
    Return top SHAP features driving yield loss/gain for a site × test_type.
    Aggregates mean absolute SHAP value across all predictions.

    Args:
        site_code: Filter to specific site. None = all.
        test_type: Filter to specific test type. None = all.
        top_n:     Number of top features to return (default 10).

    Returns:
        {"columns": [...], "rows": [...], "row_count": N}
    """
    # gold_yield_shap is a long table: row_idx, feature, shap_value, abs_shap
    # We aggregate by feature across the filtered rows
    # row_idx aligns with gold_yield_predictions index — join via subquery
    filters, params = [], []
    if site_code:
        filters.append("yp.site_id = ?"); params.append(site_code)
    if test_type:
        filters.append("yp.test_type_id = ?"); params.append(test_type.upper())

    pred_where = f"WHERE {' AND '.join(filters)}" if filters else ""

    sql = f"""
        WITH filtered_preds AS (
            SELECT rowid AS row_idx
            FROM gold_yield_predictions yp
            {pred_where}
        )
        SELECT
            ys.feature,
            AVG(ys.abs_shap)   AS mean_abs_shap,
            AVG(ys.shap_value) AS mean_shap_value,
            COUNT(*)           AS n_predictions
        FROM gold_yield_shap ys
        INNER JOIN filtered_preds fp ON ys.row_idx = fp.row_idx
        GROUP BY ys.feature
        ORDER BY mean_abs_shap DESC
        LIMIT {min(int(top_n), 50)}
    """
    try:
        rows = query(sql, params)
        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}


def get_ml_adjusted_capacity(
    site_code: str | None = None,
    test_type: str | None = None,
    month_from: int | None = None,
    month_to: int | None = None,
    limit: int = 200,
) -> dict:
    """
    Return capacity recalculated using ML-predicted yield (gold_cap_ml_adjusted).
    Shows how predicted yield shifts supply vs the static baseline.

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
        filters.append("site_code = ?"); params.append(site_code)
    if test_type:
        filters.append("test_type = ?"); params.append(test_type.upper())
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
            target_yield            AS baseline_yield,
            yield_used              AS ml_predicted_yield,
            supply_ml,
            effective_demand_qty    AS demand_qty,
            utilization_ratio_ml,
            capacity_gap_pct_ml
        FROM gold_cap_ml_adjusted
        {where}
        ORDER BY month_key, site_code, test_type
        LIMIT {min(int(limit), 2000)}
    """
    try:
        rows = query(sql, params)
        return {"columns": list(rows[0].keys()) if rows else [],
                "rows": rows, "row_count": len(rows)}
    except Exception as e:
        return {"error": str(e)}
