# Local API and UI

The approved delivery target is one FastAPI server on `127.0.0.1:8000`.

| Route | Purpose |
|---|---|
| `/` | Compact four-card application launcher |
| `/capacity-assistant/` | Capacity Assistant |
| `/chat/` | Compatibility redirect to Capacity Assistant |
| `/explorer/` | Data Explorer |
| `/decision-intelligence/` | Five ML workflow dashboards |
| `/data-operations/` | Generator and Pipeline tabs |
| `/api/health` | API, promoted data, and optional Ollama status |
| `/api/chat` | Complete Capacity Assistant response |
| `/api/chat/stream` | Cancellable SSE stream |
| `/explorer/api/*` | Read-only source, schema, data, and query APIs |

The Home page launches Data Explorer, Decision Intelligence, Capacity Assistant,
and Data Operations. The frontend remains plain HTML/CSS/JavaScript with the
Graphite/Dark Cyan palette.

## Local-only security

- Bind to loopback by default.
- Restrict CORS to configured localhost origins.
- Sanitize client errors and log details locally with correlation IDs.
- Validate and parameterize all Explorer identifiers and values.
- Escape model/tool output and allow only a small sanitized Markdown subset.
- Keep health and Explorer responsive during slow model work.
- Stop model work after client disconnect and limit concurrency for the one-model profile.

## Application composition

`capacity_home/main.py` is the only server entry point. It composes all app-owned
routes while each application keeps its own backend, frontend, configuration, and tests.

```powershell
# Start Home and every workspace on one local server.
uv run capacity-twin
```
