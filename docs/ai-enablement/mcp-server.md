# MCP Tools

Operations Assistant’s MCP layer is a structured, read-only interface over promoted telecom capacity data. Tool implementations live under `operations_assistant/agentic/mcp_server/`.

## Tool domains

- Schema and source discovery
- Capacity and bottlenecks
- Yield predictions and drivers
- OEE degradation risk
- Demand forecasts and evaluation
- CapEx simulation
- A guarded custom-query fallback

Tool names and counts are implementation details and may change during stabilization. Documentation should not promise a count without checking the current registry.

## Query contract

- Open promoted DuckDB and Raw SQLite files read-only.
- Allow one non-empty statement.
- Permit only parsed and allowlisted `SELECT` or approved `WITH`.
- Validate every source, table, column, sort key, and filter identifier.
- Parameterize values.
- Apply configured row and execution-time limits.
- Return typed rows or a sanitized error with correlation ID.
- Reopen connections when `current.json` points to a new run.

Keyword-only filtering is defense in depth, not a sufficient parser. The current implementation has read-only connection handling and query guards, but the full parsed allowlist and promoted-run refresh behavior require verification.

## Testing

Tests belong to Operations Assistant and should use temporary promoted fixtures:

```powershell
# Run Operations Assistant's local tool and API tests.
uv run pytest operations_assistant -q
```

Required cases include safe queries, empty SQL, multiple statements, mutation attempts, invalid identifiers, limits, timeouts, sanitized errors, changed run pointers, and concurrent read-only access.
