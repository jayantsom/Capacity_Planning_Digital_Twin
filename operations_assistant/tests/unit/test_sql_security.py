"""Offline tests for Operations Assistant's parsed custom-query policy."""

import duckdb
import pytest

from operations_assistant.agentic.mcp_server.sql_security import (
    SqlValidationError,
    validate_read_only_query,
)


@pytest.fixture
def connection():
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE gold_safe(id INTEGER, label VARCHAR)")
    conn.execute("INSERT INTO gold_safe VALUES (1, 'one'), (2, 'two')")
    yield conn
    conn.close()


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "SELECT * FROM gold_safe; SELECT 1",
        "SELECT * FROM gold_safe -- hidden statement",
        "SELECT /* hidden */ * FROM gold_safe",
        "INSERT INTO gold_safe VALUES (3, 'three')",
        "UPDATE gold_safe SET label = 'changed'",
        "DELETE FROM gold_safe",
        "DROP TABLE gold_safe",
        "CREATE TABLE stolen(id INTEGER)",
        "COPY gold_safe TO 'stolen.csv'",
        "ATTACH 'other.duckdb' AS other",
        "PRAGMA version",
        "SELECT * FROM read_csv_auto('secrets.csv')",
        "SELECT * FROM \"read_csv_auto\"('secrets.csv')",
        "SELECT * FROM parquet_scan('secrets.parquet')",
        "SELECT * FROM query('SELECT 1')",
        "SELECT * FROM forbidden_table",
        "SELECT secret_column FROM gold_safe",
    ],
)
def test_rejects_malicious_or_unknown_sql(connection, sql):
    with pytest.raises(SqlValidationError):
        validate_read_only_query(sql, connection, {"gold_safe"})


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, label FROM gold_safe ORDER BY id",
        "WITH safe_rows AS (SELECT id FROM gold_safe) SELECT id FROM safe_rows",
        "SELECT COUNT(*) AS count_rows FROM gold_safe",
    ],
)
def test_allows_one_bound_read_only_query(connection, sql):
    validated = validate_read_only_query(sql, connection, {"gold_safe"}, limit=1)
    rows = connection.execute(validated.sql).fetchall()
    assert len(rows) <= 1
    assert validated.limit == 1
