"""Central rules for selecting planning versions in current-state analytics."""

LATEST_VERSION_POLICY = "MAX_PLAN_AS_OF_DATE_WITHIN_BUSINESS_SERIES"


def latest_planning_version_predicate(
    table_name: str,
    *,
    column_name: str = "plan_as_of_date",
    row_alias: str | None = None,
    series_columns: tuple[str, ...] = (
        "site_code",
        "product_number",
        "test_type",
        "month_key",
    ),
) -> str:
    """Keep the latest source vintage independently within each business series."""
    row_column = f"{row_alias}.{column_name}" if row_alias else column_name
    outer = row_alias or table_name
    correlation = " AND ".join(
        f"latest.{column} IS NOT DISTINCT FROM {outer}.{column}"
        for column in series_columns
    )
    return (
        f"{row_column} = "
        f"(SELECT MAX(latest.{column_name}) FROM {table_name} AS latest "
        f"WHERE {correlation})"
    )
