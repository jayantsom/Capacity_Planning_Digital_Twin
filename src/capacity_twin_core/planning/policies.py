"""Central rules for selecting planning versions in current-state analytics."""

LATEST_VERSION_POLICY = "MAX_PLANNING_VERSION_ID"


def latest_planning_version_predicate(
    table_name: str,
    *,
    column_name: str = "planning_version_id",
    row_alias: str | None = None,
) -> str:
    """Return SQL that keeps only the latest published planning version."""
    row_column = f"{row_alias}.{column_name}" if row_alias else column_name
    return (
        f"{row_column} = "
        f"(SELECT MAX({column_name}) FROM {table_name})"
    )
