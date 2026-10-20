"""Read-only SQL and identifier policy for Data Explorer."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

import duckdb


class ExplorerSqlError(ValueError):
    """Raised when an Explorer query violates the local security policy."""


@dataclass(frozen=True)
class ParsedQuery:
    """A parsed SELECT query and its server-enforced row bound."""

    sql: str
    limit: int


_FUNCTION_RE = re.compile(r'\b"?([A-Za-z_][A-Za-z0-9_]*)"?\s*\(')
_UNSAFE_FUNCTIONS = {
    "current_setting",
    "force_install_extension",
    "getenv",
    "glob",
    "install",
    "load",
    "load_extension",
    "query",
    "query_table",
    "write_blob",
}


def clamp_limit(value: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ExplorerSqlError("Query limit must be an integer.") from error
    if parsed < 1:
        raise ExplorerSqlError("Query limit must be positive.")
    return min(parsed, maximum)


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def allow_identifier(identifier: str, allowed: Iterable[str], kind: str) -> str:
    if identifier not in set(allowed):
        raise ExplorerSqlError(f"Unknown {kind}.")
    return quote_identifier(identifier)


def _mask_and_reject_comments(sql: str) -> str:
    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(sql):
        char = sql[index]
        following = sql[index + 1] if index + 1 < len(sql) else ""
        if quote:
            output.append(char if quote == '"' else " ")
            if char == quote:
                if following == quote:
                    output.append(following if quote == '"' else " ")
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            output.append(char if quote == '"' else " ")
            index += 1
            continue
        if (char, following) in {("-", "-"), ("/", "*")}:
            raise ExplorerSqlError("SQL comments are not permitted.")
        output.append(char)
        index += 1
    if quote:
        raise ExplorerSqlError("SQL contains an unterminated quoted value.")
    return "".join(output)


def parse_read_only_sql(
    sql: str,
    allowed_tables: Iterable[str],
    *,
    limit: int,
    maximum_limit: int,
) -> ParsedQuery:
    """Use DuckDB's parser to permit one allowlisted SELECT/WITH statement."""
    if not isinstance(sql, str) or not sql.strip():
        raise ExplorerSqlError("Query cannot be empty.")
    masked = _mask_and_reject_comments(sql)
    first_keyword = re.match(r"\s*([A-Za-z_]+)", masked)
    if not first_keyword or first_keyword.group(1).lower() not in {"select", "with"}:
        raise ExplorerSqlError("Only one read-only SELECT or WITH query is permitted.")
    for match in _FUNCTION_RE.finditer(masked):
        function = match.group(1).lower()
        if (
            function in _UNSAFE_FUNCTIONS
            or function.startswith("read_")
            or function.endswith(("_scan", "_attach"))
        ):
            raise ExplorerSqlError("Query uses a function that is not permitted.")

    parser = duckdb.connect(":memory:")
    try:
        statements = parser.extract_statements(sql)
        if len(statements) != 1:
            raise ExplorerSqlError("Exactly one SQL statement is permitted.")
        statement = statements[0]
        if statement.type != duckdb.StatementType.SELECT:
            raise ExplorerSqlError("Only one read-only SELECT or WITH query is permitted.")
        references = {name.lower() for name in parser.get_table_names(statement.query)}
    except duckdb.Error as error:
        raise ExplorerSqlError("Query is not valid SQL.") from error
    finally:
        parser.close()

    allowed = {name.lower() for name in allowed_tables}
    if not references.issubset(allowed):
        raise ExplorerSqlError("Query references a table that is not permitted.")

    safe_limit = clamp_limit(limit, maximum_limit)
    normalized = statement.query.strip().rstrip(";")
    return ParsedQuery(
        f"SELECT * FROM ({normalized}) AS _explorer_bounded_query LIMIT {safe_limit}",
        safe_limit,
    )
