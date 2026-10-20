"""Offline SQL policy tests for Data Explorer."""

import pytest

from data_explorer.backend.sql_security import (
    ExplorerSqlError,
    parse_read_only_sql,
)


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "SELECT * FROM safe_table; SELECT 1",
        "SELECT * FROM safe_table -- comment",
        "SELECT /* comment */ * FROM safe_table",
        "INSERT INTO safe_table VALUES (1)",
        "UPDATE safe_table SET id=2",
        "DELETE FROM safe_table",
        "DROP TABLE safe_table",
        "CREATE TABLE stolen(id INTEGER)",
        "COPY safe_table TO 'stolen.csv'",
        "ATTACH 'other.db' AS other",
        "PRAGMA database_list",
        "SELECT * FROM read_csv('secret.csv')",
        "SELECT * FROM \"read_csv\"('secret.csv')",
        "SELECT * FROM sqlite_scan('secret.db', 'users')",
        "SELECT * FROM forbidden_table",
    ],
)
def test_rejects_malicious_sql(sql):
    with pytest.raises(ExplorerSqlError):
        parse_read_only_sql(
            sql,
            {"safe_table"},
            limit=100,
            maximum_limit=2_000,
        )


def test_wraps_valid_select_with_hard_limit():
    parsed = parse_read_only_sql(
        "WITH rows AS (SELECT id FROM safe_table) SELECT id FROM rows",
        {"safe_table"},
        limit=25,
        maximum_limit=2_000,
    )
    assert parsed.limit == 25
    assert parsed.sql.endswith("LIMIT 25")
