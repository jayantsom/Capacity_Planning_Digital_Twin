# FastAPI Backend

> **Chat API**: `backend/main.py` — port 8000
> **Data Explorer API**: `backend/explorer/main.py` — port 8001
> **Run**: `uv run python -m backend.main` | `uv run uvicorn backend.explorer.main:app --port 8001`

---

## Chat Backend (`backend/main.py`)

### What does it do?

Bridges the frontend chat UI and the LangGraph agent system. Accepts a user question, runs it through the compiled graph, and streams the response as Server-Sent Events (SSE).

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serves `frontend/index.html` |
| `GET` | `/api/health` | `{status, agents, version}` |
| `GET` | `/api/agents` | Agent registry: name, description, tool list |
| `POST` | `/api/chat` | Full synchronous JSON response |
| `POST` | `/api/chat/stream` | SSE streaming response |

### Static file serving

```python
app.mount("/static", StaticFiles(directory="frontend"), name="static")
```

`index.html` references assets as `/static/style.css` and `/static/app.js`.

---

### `/api/chat` — synchronous

**Request**:
```json
{ "question": "Which sites have CRITICAL bottlenecks?", "session_id": null }
```

**Response** (`ChatResponse`):
```json
{
  "answer":         "Based on the analysis...",
  "agent":          "capacity",
  "tool_results":   [{"tool": "get_bottleneck_analysis", "row_count": 47, "columns": [...]}],
  "pipeline_steps": [{"step": "router", "detail": "→ CAPACITY agent"}, ...],
  "error":          null
}
```

---

### `/api/chat/stream` — SSE streaming

The generator function `event_stream()` consumes `graph.stream(..., stream_mode="updates")` and emits events as each LangGraph node completes.

**SSE event types**:

| `type` | When emitted | `data` fields |
|---|---|---|
| `pipeline` | Each node transition | `step`, `detail`, `agent` (router); `tool`, `row_count`, `columns` (mcp_tool) |
| `token` | Each word of the answer | `"word "` |
| `done` | Graph complete | `agent`, `tools_called`, `tool_count` |
| `error` | Any exception | error string |

**Event format** (newline-delimited):
```
data: {"type": "pipeline", "data": {"step": "router", "detail": "→ CAPACITY agent", "agent": "capacity"}}

data: {"type": "pipeline", "data": {"step": "mcp_tool", "detail": "`get_bottleneck_analysis` → DuckDB → 47 rows", "tool": "get_bottleneck_analysis", "row_count": 47}}

data: {"type": "token", "data": "Based "}
data: {"type": "token", "data": "on "}

data: {"type": "done", "data": {"agent": "capacity", "tools_called": ["get_bottleneck_analysis"], "tool_count": 1}}
```

**Token streaming**: the completed `answer` string from the agent is split by space and emitted word-by-word. True token streaming would require Ollama's streaming API at the synthesis call level — not currently implemented.

---

### Pydantic models (`backend/models.py`)

| Model | Fields |
|---|---|
| `ChatRequest` | `question: str`, `session_id: str \| None` |
| `ToolResult` | `tool`, `row_count`, `columns`, `error` |
| `PipelineStep` | `step`, `detail` |
| `ChatResponse` | `answer`, `agent`, `tool_results`, `pipeline_steps`, `error` |

---

### CORS configuration

```python
app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

Permissive for local development. Restrict `allow_origins` before any network-exposed deployment.

---

## Data Explorer Backend (`backend/explorer/main.py`)

### What does it do?

Auto-discovers all SQLite databases in `data/` and the DuckDB analytics database, then exposes them via a REST API for the Data Explorer frontend to browse.

### Source discovery

On startup, `_discover_sources()` scans `data/*.db` (SQLite) and `data/capacity_planning_twin.duckdb` (DuckDB). Sources are stored in the module-level `SOURCES` dict — no database restart needed to pick up new files.

### Layer classification

```python
def _table_layer(table_name: str) -> str:
    if table_name.startswith("brnz_"):              return "bronze"
    if table_name.startswith("slvr_"):              return "silver"
    if table_name.startswith(("gold_", "srv_vw_")): return "gold"
    return "raw"
```

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/explorer/` | Serves `frontend/explorer/index.html` |
| `GET` | `/explorer/api/sources` | All sources with tables grouped by layer |
| `GET` | `/explorer/api/schema/{source_id}/{table}` | Columns + types + row count |
| `GET` | `/explorer/api/data/{source_id}/{table}` | Paginated rows; supports `filters` (JSON), `sort_col`, `sort_dir`, `page`, `page_size` |
| `GET` | `/explorer/api/distinct/{source_id}/{table}/{col}` | Distinct values for a column (max 500) |
| `POST` | `/explorer/api/query/{source_id}` | Execute any `SELECT`; body: `{sql, limit}` |

### Query parameter handling

The `/data/` endpoint accepts `filters` as a JSON-encoded string: `?filters={"site_code":"SG01"}`. This allows multi-column filtering without URL complexity.

**DuckDB uses positional parameters** (`$1`, `$2`); **SQLite uses `?`**. The endpoint rebuilds the WHERE clause with the correct placeholder style per source type.

### Safety

`_is_safe_sql()` checks the first token of the SQL string:
```python
def _is_safe_sql(sql):
    first = sql.strip().split()[0].lower()
    return first in ("select", "with", "explain")
```

DuckDB source additionally connects `read_only=True`.

### `/explorer/api/sources` response shape

```json
[
  {
    "id": "raw_sites", "label": "Sites", "type": "sqlite",
    "layer": "raw", "color": "#6e7681",
    "tables": [{"name": "sites", "layer": "raw"}]
  },
  {
    "id": "duckdb_analytics", "label": "Analytics DB",
    "type": "duckdb", "layer": "multi",
    "layers": {
      "bronze": {"label": "Bronze", "color": "#b45309",
                 "tables": [{"name": "brnz_sites", "layer": "bronze"}, ...]},
      "silver": {...},
      "gold":   {...}
    }
  }
]
```

---

## Shared design decisions

**Why FastAPI?** Native async support, SSE via `StreamingResponse`, Pydantic v2 validation, auto-generated OpenAPI docs at `/docs`.

**Why separate ports (8000 / 8001)?** Clean separation of concerns — chat API and data explorer are independent applications. No route prefix conflicts.

**Why `read_only=True` everywhere?** DuckDB supports concurrent readers but only one writer. Enforcing read-only at the connection level prevents any accidental writes from API layer bugs.
