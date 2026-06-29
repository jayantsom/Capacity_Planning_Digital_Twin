"""
Data Explorer Backend
=====================
FastAPI app exposing SQLite (raw layer) and DuckDB (bronze/silver/gold) data.

Endpoints:
  GET  /explorer/api/sources          — list all data sources + their tables
  GET  /explorer/api/schema/{source}/{table}   — columns + types
  GET  /explorer/api/data/{source}/{table}     — paginated rows with filters
  GET  /explorer/api/distinct/{source}/{table}/{col} — distinct values for a column
  POST /explorer/api/query/{source}   — run a custom SELECT
  GET  /explorer/                     — serves explorer index.html
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PROJECT_ROOT  = Path(__file__).resolve().parents[2]
DATA_DIR      = PROJECT_ROOT / "data"
FRONTEND_DIR  = PROJECT_ROOT / "frontend" / "explorer"

# ── Source registry ────────────────────────────────────────────────────────────

def _discover_sources() -> dict[str, dict]:
    """
    Discover all SQLite databases in DATA_DIR and DuckDB analytics DB.
    Returns a dict of source_id → {type, path, layer, label, color}.
    """
    sources = {}

    # SQLite raw databases
    RAW_COLORS = {
        "sites":         "#6e7681",
        "products":      "#6e7681",
        "equipment":     "#6e7681",
        "calendar":      "#6e7681",
        "suppliers":     "#6e7681",
        "test_types":    "#6e7681",
        "demand":        "#6e7681",
        "yield_data":    "#6e7681",
        "oee_data":      "#6e7681",
        "gcm_config":    "#6e7681",
    }
    raw_sqlite_dir = DATA_DIR / "raw" / "sqlite"
    if raw_sqlite_dir.exists():
        for sqlite_path in sorted(raw_sqlite_dir.glob("*.db")):
            sid = sqlite_path.stem
            sources[f"raw_{sid}"] = {
                "type":   "sqlite",
                "path":   str(sqlite_path),
                "layer":  "raw",
                "label":  sid.replace("_", " ").title(),
                "color":  RAW_COLORS.get(sid, "#6e7681"),
            }

    # DuckDB analytics (bronze / silver / gold layers by prefix)
    duckdb_path = DATA_DIR / "capacity_planning_twin.duckdb"
    if duckdb_path.exists():
        sources["duckdb_analytics"] = {
            "type":  "duckdb",
            "path":  str(duckdb_path),
            "layer": "multi",   # tables have brnz_ / slvr_ / gold_ / srv_vw_ prefixes
            "label": "Analytics DB",
            "color": "#58a6ff",
        }

    return sources


SOURCES = _discover_sources()

LAYER_META = {
    "raw":    {"label": "Raw",    "color": "#6e7681", "prefix": []},
    "bronze": {"label": "Bronze", "color": "#b45309", "prefix": ["brnz_"]},
    "silver": {"label": "Silver", "color": "#64748b", "prefix": ["slvr_"]},
    "gold":   {"label": "Gold",   "color": "#d97706", "prefix": ["gold_", "srv_vw_"]},
}

def _table_layer(table_name: str) -> str:
    if table_name.startswith("brnz_"):  return "bronze"
    if table_name.startswith("slvr_"):  return "silver"
    if table_name.startswith(("gold_", "srv_vw_")): return "gold"
    return "raw"

# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_duckdb(source_id: str) -> duckdb.DuckDBPyConnection:
    src = SOURCES.get(source_id)
    if not src or src["type"] != "duckdb":
        raise HTTPException(404, f"DuckDB source not found: {source_id}")
    return duckdb.connect(src["path"], read_only=True)


def _get_sqlite(source_id: str) -> sqlite3.Connection:
    src = SOURCES.get(source_id)
    if not src or src["type"] != "sqlite":
        raise HTTPException(404, f"SQLite source not found: {source_id}")
    conn = sqlite3.connect(src["path"])
    conn.row_factory = sqlite3.Row
    return conn


def _is_safe_sql(sql: str) -> bool:
    first = sql.strip().split()[0].lower() if sql.strip() else ""
    return first in ("select", "with", "explain")


def _duckdb_tables(conn: duckdb.DuckDBPyConnection) -> list[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' ORDER BY table_name"
    ).fetchall()
    return [r[0] for r in rows]


def _sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _duckdb_schema(conn: duckdb.DuckDBPyConnection, table: str) -> list[dict]:
    rows = conn.execute(f"DESCRIBE {table}").fetchall()
    return [{"name": r[0], "type": r[1]} for r in rows]


def _sqlite_schema(conn: sqlite3.Connection, table: str) -> list[dict]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [{"name": r[1], "type": r[2] or "TEXT"} for r in rows]


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Data Explorer API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

if FRONTEND_DIR.exists():
    app.mount("/explorer/static", StaticFiles(directory=str(FRONTEND_DIR)), name="explorer_static")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/explorer/")
async def explorer_index():
    idx = FRONTEND_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse({"error": "Frontend not found"}, status_code=404)


@app.get("/explorer/api/sources")
async def get_sources():
    """List all data sources with their tables, grouped by layer."""
    result = []
    for sid, src in SOURCES.items():
        try:
            if src["type"] == "sqlite":
                conn   = _get_sqlite(sid)
                tables = _sqlite_tables(conn)
                conn.close()
                layer  = "raw"
                result.append({
                    "id": sid, "label": src["label"],
                    "type": src["type"], "layer": layer,
                    "color": src["color"],
                    "tables": [{"name": t, "layer": "raw"} for t in tables],
                })
            else:
                conn   = _get_duckdb(sid)
                tables = _duckdb_tables(conn)
                conn.close()
                # Group by layer
                grouped: dict[str, list] = {"bronze": [], "silver": [], "gold": []}
                for t in tables:
                    lyr = _table_layer(t)
                    if lyr in grouped:
                        grouped[lyr].append({"name": t, "layer": lyr})
                result.append({
                    "id": sid, "label": src["label"],
                    "type": src["type"], "layer": "multi",
                    "color": src["color"],
                    "layers": {
                        k: {"tables": v, **LAYER_META[k]}
                        for k, v in grouped.items()
                        if v
                    },
                })
        except Exception as e:
            result.append({"id": sid, "label": src["label"],
                           "error": str(e), "tables": []})
    return result


@app.get("/explorer/api/schema/{source_id}/{table}")
async def get_schema(source_id: str, table: str):
    src = SOURCES.get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    try:
        if src["type"] == "sqlite":
            conn    = _get_sqlite(source_id)
            columns = _sqlite_schema(conn, table)
            row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            conn.close()
        else:
            conn    = _get_duckdb(source_id)
            columns = _duckdb_schema(conn, table)
            row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            conn.close()
        return {
            "source": source_id, "table": table,
            "layer": _table_layer(table),
            "columns": columns, "row_count": row_count,
        }
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/explorer/api/data/{source_id}/{table}")
async def get_data(
    source_id: str,
    table: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    filters: str = Query("{}"),   # JSON string of {col: value}
    sort_col: str | None = None,
    sort_dir: str = "asc",
):
    src = SOURCES.get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")

    try:
        filter_dict = json.loads(filters)
    except Exception:
        filter_dict = {}

    safe_sort_dir = "ASC" if sort_dir.lower() != "desc" else "DESC"
    offset = (page - 1) * page_size

    # Build WHERE clause
    where_parts, params = [], []
    for col, val in filter_dict.items():
        if val not in (None, "", []):
            if isinstance(val, list):
                placeholders = ",".join(["?" if src["type"]=="sqlite" else "$"+str(i+len(params)+1) for i, _ in enumerate(val)])
                where_parts.append(f'"{col}" IN ({placeholders})')
                params.extend(val)
            else:
                ph = "?" if src["type"] == "sqlite" else f"${len(params)+1}"
                where_parts.append(f'"{col}" = {ph}')
                params.append(val)

    where_clause  = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    order_clause  = f'ORDER BY "{sort_col}" {safe_sort_dir}' if sort_col else ""

    try:
        if src["type"] == "sqlite":
            conn = _get_sqlite(source_id)
            total = conn.execute(f"SELECT COUNT(*) FROM {table} {where_clause}", params).fetchone()[0]
            rows  = conn.execute(
                f"SELECT * FROM {table} {where_clause} {order_clause} LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()
            columns = [d[0] for d in conn.execute(f"SELECT * FROM {table} LIMIT 0").description]
            conn.close()
            data = [dict(zip(columns, r)) for r in rows]
        else:
            # DuckDB uses $1,$2 positional params
            conn = _get_duckdb(source_id)
            if where_parts:
                # rebuild with DuckDB-style params
                wp2, params2 = [], []
                for col, val in filter_dict.items():
                    if val not in (None, "", []):
                        if isinstance(val, list):
                            phs = ",".join([f"${i+len(params2)+1}" for i in range(len(val))])
                            wp2.append(f'"{col}" IN ({phs})')
                            params2.extend(val)
                        else:
                            wp2.append(f'"{col}" = ${len(params2)+1}')
                            params2.append(val)
                where_clause = f"WHERE {' AND '.join(wp2)}"
                params = params2

            total_rel = conn.execute(f"SELECT COUNT(*) FROM {table} {where_clause}", params)
            total     = total_rel.fetchone()[0]
            rel = conn.execute(
                f"SELECT * FROM {table} {where_clause} {order_clause} "
                f"LIMIT {page_size} OFFSET {offset}", params
            )
            cols = [d[0] for d in rel.description]
            data = [dict(zip(cols, r)) for r in rel.fetchall()]
            conn.close()

        return {
            "source": source_id, "table": table,
            "page": page, "page_size": page_size,
            "total": total, "total_pages": max(1, -(-total // page_size)),
            "columns": list(data[0].keys()) if data else [],
            "rows": data,
        }
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/explorer/api/distinct/{source_id}/{table}/{col}")
async def get_distinct(source_id: str, table: str, col: str, limit: int = 200):
    src = SOURCES.get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    try:
        sql = f'SELECT DISTINCT "{col}" FROM {table} WHERE "{col}" IS NOT NULL ORDER BY "{col}" LIMIT {min(limit,500)}'
        if src["type"] == "sqlite":
            conn   = _get_sqlite(source_id)
            rows   = conn.execute(sql).fetchall()
            conn.close()
            values = [r[0] for r in rows]
        else:
            conn   = _get_duckdb(source_id)
            rows   = conn.execute(sql).fetchall()
            conn.close()
            values = [r[0] for r in rows]
        return {"column": col, "values": values, "count": len(values)}
    except Exception as e:
        raise HTTPException(400, str(e))


class QueryRequest(BaseModel):
    sql: str
    limit: int = 500


@app.post("/explorer/api/query/{source_id}")
async def run_query(source_id: str, req: QueryRequest):
    src = SOURCES.get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    if not _is_safe_sql(req.sql):
        raise HTTPException(400, "Only SELECT queries are permitted.")
    limit = min(req.limit, 2000)
    sql   = req.sql.rstrip().rstrip(";")
    if "limit" not in sql.lower():
        sql = f"{sql} LIMIT {limit}"
    try:
        if src["type"] == "sqlite":
            conn    = _get_sqlite(source_id)
            cur     = conn.execute(sql)
            cols    = [d[0] for d in cur.description]
            rows    = [dict(zip(cols, r)) for r in cur.fetchall()]
            conn.close()
        else:
            conn    = _get_duckdb(source_id)
            rel     = conn.execute(sql)
            cols    = [d[0] for d in rel.description]
            rows    = [dict(zip(cols, r)) for r in rel.fetchall()]
            conn.close()
        return {"columns": cols, "rows": rows, "row_count": len(rows)}
    except Exception as e:
        raise HTTPException(400, str(e))


if __name__ == "__main__":
    import uvicorn, sys
    sys.path.insert(0, str(PROJECT_ROOT))
    uvicorn.run("backend.explorer.main:app", host="127.0.0.1", port=8001,
                reload=True, reload_dirs=[str(PROJECT_ROOT / "backend")])
