"""Parsed, allowlisted SQL validation for Operations Assistant's read-only tools."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

import duckdb

MAX_QUERY_ROWS = 2_000
DEFAULT_QUERY_ROWS = 500

# These functions can access files, networks, extensions, settings, or dynamic SQL.
_UNSAFE_FUNCTION_PATTERNS = (
    re.compile(r"^read_", re.IGNORECASE),
    re.compile(r".*_scan$", re.IGNORECASE),
    re.compile(r".*_attach$", re.IGNORECASE),
)
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
_FUNCTION_RE = re.compile(r'\b"?([A-Za-z_][A-Za-z0-9_]*)"?\s*\(')


class SqlValidationError(ValueError):
    """Raised when a custom query violates the local read-only policy."""


@dataclass(frozen=True)
class ValidatedQuery:
    """A parsed query wrapped with a server-enforced outer row limit."""

    sql: str
    tables: frozenset[str]
    limit: int


def clamp_limit(value: int, *, maximum: int = MAX_QUERY_ROWS) -> int:
    """Return a positive row limit within the server's hard cap."""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise SqlValidationError("Query limit must be an integer.") from error
    if parsed < 1:
        raise SqlValidationError("Query limit must be positive.")
    return min(parsed, maximum)


def quote_identifier(identifier: str) -> str:
    """Quote an identifier only after it has passed an allowlist check."""
    return '"' + identifier.replace('"', '""') + '"'


def require_identifier(identifier: str, allowed: Iterable[str], kind: str) -> str:
    """Require an exact identifier match from a database-derived allowlist."""
    allowed_set = set(allowed)
    if identifier not in allowed_set:
        raise SqlValidationError(f"Unknown {kind}.")
    return quote_identifier(identifier)


def _mask_literals_and_reject_comments(sql: str) -> str:
    """Mask quoted values while rejecting SQL comments outside quoted text."""
    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""
        if quote:
            output.append(char if quote == '"' else " ")
            if char == quote:
                if next_char == quote:
                    output.append(next_char if quote == '"' else " ")
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
        if char == "-" and next_char == "-":
            raise SqlValidationError("SQL comments are not permitted.")
        if char == "/" and next_char == "*":
            raise SqlValidationError("SQL comments are not permitted.")
        output.append(char)
        index += 1
    if quote:
        raise SqlValidationError("SQL contains an unterminated quoted value.")
    return "".join(output)


def _reject_unsafe_functions(masked_sql: str) -> None:
    for match in _FUNCTION_RE.finditer(masked_sql):
        function_name = match.group(1).lower()
        if function_name in _UNSAFE_FUNCTIONS or any(
            pattern.fullmatch(function_name) for pattern in _UNSAFE_FUNCTION_PATTERNS
        ):
            raise SqlValidationError("Query uses a function that is not permitted.")


def validate_read_only_query(
    sql: str,
    connection: duckdb.DuckDBPyConnection,
    allowed_tables: Iterable[str],
    *,
    limit: int = DEFAULT_QUERY_ROWS,
) -> ValidatedQuery:
    """Parse, bind, allowlist, and bound one DuckDB SELECT/WITH query."""
    if not isinstance(sql, str) or not sql.strip():
        raise SqlValidationError("Query cannot be empty.")

    masked_sql = _mask_literals_and_reject_comments(sql)
    first_keyword = re.match(r"\s*([A-Za-z_]+)", masked_sql)
    if not first_keyword or first_keyword.group(1).lower() not in {"select", "with"}:
        raise SqlValidationError("Only one read-only SELECT or WITH query is permitted.")
    _reject_unsafe_functions(masked_sql)
    try:
        statements = connection.extract_statements(sql)
    except duckdb.Error as error:
        raise SqlValidationError("Query is not valid SQL.") from error
    if len(statements) != 1:
        raise SqlValidationError("Exactly one SQL statement is permitted.")

    statement = statements[0]
    if statement.type != duckdb.StatementType.SELECT:
        raise SqlValidationError("Only one read-only SELECT or WITH query is permitted.")

    allowed = {name.lower() for name in allowed_tables}
    try:
        referenced = {name.lower() for name in connection.get_table_names(statement.query)}
    except duckdb.Error as error:
        raise SqlValidationError("Query identifiers could not be validated.") from error
    if not referenced.issubset(allowed):
        raise SqlValidationError("Query references a table that is not permitted.")

    safe_limit = clamp_limit(limit)
    normalized = statement.query.strip().rstrip(";")
    bounded = f"SELECT * FROM ({normalized}) AS _operations_assistant_bounded_query LIMIT {safe_limit}"

    # EXPLAIN invokes DuckDB's binder, so unknown/ambiguous column identifiers fail
    # before the query runs. External-access functions were rejected above.
    try:
        connection.execute(f"EXPLAIN {bounded}")
    except duckdb.Error as error:
        raise SqlValidationError("Query contains invalid or disallowed identifiers.") from error

    return ValidatedQuery(bounded, frozenset(referenced), safe_limit)
