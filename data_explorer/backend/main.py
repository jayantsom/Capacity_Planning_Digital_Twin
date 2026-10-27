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

import ipaddress
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import duckdb
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from capacity_twin_core.analytics import TimeGrain, supported_grains
from capacity_twin_core.comparison import (
    get_comparison_window,
    resolve_time_column,
)
from capacity_twin_core.runtime.database_paths import (
    get_active_run_pointer,
    get_control_run_pointer,
    get_runtime_home,
    load_app_config,
    load_config,
)
from data_explorer.backend.sql_security import (
    ExplorerSqlError,
    allow_identifier,
    clamp_limit,
    parse_read_only_sql,
)

APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = get_runtime_home()
FRONTEND_DIR = APP_DIR / "frontend"
PIPELINE_CONFIG = load_app_config("data_operations.pipeline")
EXPLORER_CONFIG = load_app_config("data_explorer")
QUERY_CONFIG = EXPLORER_CONFIG.get("query", {})
QUERY_TIMEOUT_SECONDS = float(QUERY_CONFIG.get("timeout_seconds", 15))
MAX_QUERY_LIMIT = int(QUERY_CONFIG.get("maximum_limit", 2_000))

# ── Source registry ────────────────────────────────────────────────────────────

def _active_artifact_root() -> Path | None:
    """Resolve the current promoted artifact on every source refresh."""
    pointer = get_active_run_pointer(DATA_DIR)
    if not pointer.is_file():
        return None
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    serving_database = payload.get("serving_database")
    if serving_database:
        serving_path = Path(serving_database)
        if not serving_path.is_absolute():
            serving_path = DATA_DIR / serving_path
        return serving_path.parent
    configured = payload.get("artifact_path") or payload.get("path")
    if configured:
        root = Path(configured)
        return root if root.is_absolute() else DATA_DIR / root
    run_id = (
        payload.get("active_run_id")
        or payload.get("run_id")
        or payload.get("current_run_id")
    )
    return DATA_DIR / "artifacts" / str(run_id) if run_id else None


def _discover_sources() -> dict[str, dict]:
    """Discover every project database without exposing engine internals."""
    sources: dict[str, dict] = {}
    artifact_root = _active_artifact_root()
    raw_sqlite_dir = (
        artifact_root / "raw" / "sqlite"
        if artifact_root and (artifact_root / "raw" / "sqlite").is_dir()
        else DATA_DIR / "raw" / "sqlite"
    )
    if raw_sqlite_dir.exists():
        for sqlite_path in sorted(raw_sqlite_dir.glob("*.db")):
            sid = sqlite_path.stem
            sources[f"raw_{sid}"] = {
                "type":   "sqlite",
                "path":   str(sqlite_path),
                "layer":  "raw",
                "label":  sid.replace("_", " ").title(),
                "color":  LAYER_META["raw"]["color"],
                "available": True,
            }
    for filename in load_config()["databases"]["raw"].values():
        sqlite_path = raw_sqlite_dir / filename
        sid = sqlite_path.stem
        sources.setdefault(
            f"raw_{sid}",
            {
                "type": "sqlite",
                "path": str(sqlite_path),
                "layer": "raw",
                "label": sid.replace("_", " ").title(),
                "color": LAYER_META["raw"]["color"],
                "available": False,
            },
        )

    control_pointer = get_control_run_pointer(DATA_DIR)
    control_path: Path | None = None
    control_run_id = None
    if control_pointer.is_file():
        try:
            payload = json.loads(control_pointer.read_text(encoding="utf-8"))
            control_path = Path(payload["database"])
            control_run_id = payload.get("control_run_id")
        except (OSError, KeyError, json.JSONDecodeError):
            control_path = None
    sources["duckdb_control"] = {
        "type": "duckdb",
        "path": str(control_path) if control_path else "",
        "layer": "control",
        "label": "Control Reference DB",
        "color": LAYER_META["control"]["color"],
        "available": bool(control_path and control_path.is_file()),
        "run_id": control_run_id,
    }

    # Register each physical medallion database, including missing expected layers.
    database_names = PIPELINE_CONFIG["databases"]
    for layer in ("bronze", "silver", "gold", "serving"):
        database_name = database_names[layer]
        candidate = (artifact_root / database_name) if artifact_root else None
        duckdb_path = (
            candidate
            if candidate is not None and candidate.is_file()
            else DATA_DIR / database_name
        )
        sources[f"duckdb_{layer}"] = {
            "type": "duckdb",
            "path": str(duckdb_path),
            "layer": layer,
            "label": f"{layer.title()} DB",
            "color": LAYER_META[layer]["color"],
            "available": duckdb_path.is_file(),
        }

    ml_pointer = DATA_DIR / "ml_current.json"
    ml_path: Path | None = None
    ml_run_id = None
    if ml_pointer.is_file():
        try:
            payload = json.loads(ml_pointer.read_text(encoding="utf-8"))
            ml_path = (DATA_DIR / payload["database"]).resolve()
            ml_run_id = payload.get("run_id")
        except (OSError, KeyError, json.JSONDecodeError):
            ml_path = None
    sources["duckdb_ml"] = {
        "type": "duckdb",
        "path": str(ml_path) if ml_path else "",
        "layer": "ml",
        "label": "ML Publication DB",
        "color": LAYER_META["ml"]["color"],
        "available": bool(ml_path and ml_path.is_file()),
        "run_id": ml_run_id,
    }

    return sources


LAYER_META = {
    "raw":    {"label": "Raw",    "color": "#315f8f", "prefix": []},
    "control": {"label": "Control", "color": "#5b4b8a", "prefix": []},
    "bronze": {"label": "Bronze", "color": "#b45309", "prefix": ["brnz_"]},
    "silver": {"label": "Silver", "color": "#64748b", "prefix": ["slvr_"]},
    "gold":   {"label": "Gold",   "color": "#d97706", "prefix": ["gold_", "srv_vw_"]},
    "serving": {"label": "Serving", "color": "#006d77", "prefix": ["srv_vw_"]},
    "ml": {"label": "ML", "color": "#7c3aed", "prefix": ["gold_"]},
}

def _table_layer(table_name: str) -> str:
    if table_name.startswith("brnz_"):  return "bronze"
    if table_name.startswith("slvr_"):  return "silver"
    if table_name.startswith(("gold_", "srv_vw_")): return "gold"
    return "raw"

# ── DB helpers ─────────────────────────────────────────────────────────────────

def _get_duckdb(source_id: str) -> duckdb.DuckDBPyConnection:
    src = _discover_sources().get(source_id)
    if not src or src["type"] != "duckdb" or not src.get("available"):
        raise HTTPException(404, f"DuckDB source not found: {source_id}")
    return duckdb.connect(src["path"], read_only=True)


def _get_sqlite(source_id: str) -> sqlite3.Connection:
    src = _discover_sources().get(source_id)
    if not src or src["type"] != "sqlite" or not src.get("available", True):
        raise HTTPException(404, f"SQLite source not found: {source_id}")
    uri = f"{Path(src['path']).resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _duckdb_objects(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
        ORDER BY table_schema, table_name
        """
    ).fetchall()
    return [
        {
            "name": row[1] if row[0] == "main" else f"{row[0]}.{row[1]}",
            "schema": row[0],
            "object_type": "VIEW" if "VIEW" in row[2] else "TABLE",
        }
        for row in rows
    ]


def _duckdb_tables(conn: duckdb.DuckDBPyConnection) -> list[str]:
    return [item["name"] for item in _duckdb_objects(conn)]


def _quote_duckdb_object(object_name: str, allowed: list[str]) -> str:
    if object_name not in set(allowed):
        raise ExplorerSqlError("Unknown table.")
    return ".".join(f'"{part}"' for part in object_name.split("."))


def _sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _duckdb_schema(conn: duckdb.DuckDBPyConnection, table: str) -> list[dict]:
    safe_table = _quote_duckdb_object(table, _duckdb_tables(conn))
    rows = conn.execute(f"DESCRIBE {safe_table}").fetchall()
    return [{"name": r[0], "type": r[1]} for r in rows]


def _sqlite_schema(conn: sqlite3.Connection, table: str) -> list[dict]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [{"name": r[1], "type": r[2] or "TEXT"} for r in rows]


def _execute_duckdb_query(
    conn: duckdb.DuckDBPyConnection, sql: str
) -> tuple[list[str], list[dict]]:
    """Bind and execute with a hard interrupt deadline."""
    conn.execute(f"EXPLAIN {sql}")
    timed_out = threading.Event()

    def interrupt() -> None:
        timed_out.set()
        conn.interrupt()

    timer = threading.Timer(QUERY_TIMEOUT_SECONDS, interrupt)
    timer.daemon = True
    timer.start()
    try:
        relation = conn.execute(sql)
        columns = [description[0] for description in relation.description]
        rows = [dict(zip(columns, row)) for row in relation.fetchall()]
        return columns, rows
    except duckdb.Error as error:
        if timed_out.is_set():
            raise TimeoutError("Query timed out.") from error
        raise
    finally:
        timer.cancel()


def _execute_sqlite_query(
    conn: sqlite3.Connection, sql: str
) -> tuple[list[str], list[dict]]:
    """Bind and execute with SQLite's progress-handler deadline."""
    conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
    deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1_000)
    try:
        cursor = conn.execute(sql)
        columns = [description[0] for description in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return columns, rows
    finally:
        conn.set_progress_handler(None, 0)


# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Data Explorer API", version="1.0.0")


def _is_loopback_host(value: str) -> bool:
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _allowed_origins() -> list[str]:
    origins = EXPLORER_CONFIG.get("server", {}).get("allowed_origins", [])
    if not origins or "*" in origins:
        raise RuntimeError("Data Explorer requires explicit localhost CORS origins.")
    for origin in origins:
        parsed = urlparse(origin)
        local = bool(parsed.hostname and _is_loopback_host(parsed.hostname))
        if parsed.scheme not in {"http", "https"} or not local:
            raise RuntimeError("Data Explorer CORS origins must be localhost-only.")
    return origins


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(ExplorerSqlError)
async def explorer_sql_error_handler(
    _request: Request, error: ExplorerSqlError
) -> JSONResponse:
    """Return policy failures as bounded client-safe errors."""
    return JSONResponse({"detail": str(error)}, status_code=400)

if FRONTEND_DIR.exists():
    app.mount("/explorer/static", StaticFiles(directory=str(FRONTEND_DIR)), name="explorer_static")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/explorer/")
def explorer_index():
    idx = FRONTEND_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return JSONResponse({"error": "Frontend not found"}, status_code=404)


@app.get("/explorer/api/sources")
def get_sources():
    """List every project table/view and report missing expected databases."""
    result = []
    for sid, src in _discover_sources().items():
        if not src.get("available", True):
            result.append(
                {
                    "id": sid,
                    "label": src["label"],
                    "type": src["type"],
                    "layer": src["layer"],
                    "color": src["color"],
                    "status": "NOT GENERATED",
                    "run_id": src.get("run_id"),
                    "tables": [],
                }
            )
            continue
        try:
            if src["type"] == "sqlite":
                conn   = _get_sqlite(sid)
                tables = _sqlite_tables(conn)
                conn.close()
                result.append({
                    "id": sid, "label": src["label"],
                    "type": src["type"], "layer": "raw",
                    "color": src["color"],
                    "status": "READY",
                    "tables": [
                        {"name": table, "layer": "raw", "object_type": "TABLE"}
                        for table in tables
                        if table != "sqlite_sequence"
                    ],
                })
            else:
                conn   = _get_duckdb(sid)
                objects = _duckdb_objects(conn)
                tables = []
                for item in objects:
                    safe_table = _quote_duckdb_object(
                        item["name"], [obj["name"] for obj in objects]
                    )
                    row_count = conn.execute(
                        f"SELECT COUNT(*) FROM {safe_table}"
                    ).fetchone()[0]
                    tables.append(
                        {
                            **item,
                            "layer": src["layer"],
                            "row_count": int(row_count),
                        }
                    )
                conn.close()
                result.append({
                    "id": sid, "label": src["label"],
                    "type": src["type"], "layer": src["layer"],
                    "color": src["color"],
                    "status": "READY",
                    "run_id": src.get("run_id"),
                    "tables": tables,
                })
        except Exception:  # noqa: BLE001 - source failures are reported per source
            result.append({
                "id": sid,
                "label": src["label"],
                "layer": src["layer"],
                "status": "UNAVAILABLE",
                "error": "Source is unavailable.",
                "tables": [],
            })
    return result


@app.get("/explorer/api/schema/{source_id}/{table}")
def get_schema(source_id: str, table: str):
    src = _discover_sources().get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    try:
        if src["type"] == "sqlite":
            conn = _get_sqlite(source_id)
            try:
                tables = _sqlite_tables(conn)
                safe_table = allow_identifier(table, tables, "table")
                columns = _sqlite_schema(conn, safe_table)
                row_count = conn.execute(
                    f"SELECT COUNT(*) FROM {safe_table}"
                ).fetchone()[0]
            finally:
                conn.close()
        else:
            conn = _get_duckdb(source_id)
            try:
                tables = _duckdb_tables(conn)
                safe_table = _quote_duckdb_object(table, tables)
                columns = _duckdb_schema(conn, table)
                row_count = conn.execute(
                    f"SELECT COUNT(*) FROM {safe_table}"
                ).fetchone()[0]
            finally:
                conn.close()
        native_grain = (
            TimeGrain.DAY
            if any(
                column["name"]
                in {"execution_date", "event_date", "event_timestamp", "period_start"}
                for column in columns
            )
            else TimeGrain.MONTH
            if any(
                column["name"] in {"month", "month_key", "forecast_month_key"}
                for column in columns
            )
            else TimeGrain.NONE
        )
        is_operational_rollup = any(
            column["name"] == "period_grain" for column in columns
        )
        grain_options = (
            (TimeGrain.WEEK, TimeGrain.MONTH)
            if is_operational_rollup
            else supported_grains(native_grain)
        )
        return {
            "source": source_id, "table": table,
            "layer": src["layer"],
            "columns": columns, "row_count": row_count,
            "native_grain": native_grain.value,
            "supported_grains": [
                grain.value for grain in grain_options
            ],
            "comparison_supported": (
                src["type"] == "duckdb"
                and src["layer"] in {"silver", "gold", "serving", "ml"}
                and resolve_time_column({column["name"] for column in columns})
                is not None
            ),
        }
    except ExplorerSqlError as error:
        raise HTTPException(400, str(error)) from error
    except Exception as error:
        raise HTTPException(400, "Schema request could not be completed.") from error


@app.get("/explorer/api/data/{source_id}/{table}")
def get_data(
    source_id: str,
    table: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    filters: str = Query("{}"),   # JSON string of {col: value}
    sort_col: str | None = None,
    sort_dir: str = "asc",
    window: Literal["total", "band_1", "band_2"] = "total",
):
    src = _discover_sources().get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")

    metadata_conn = (
        _get_sqlite(source_id) if src["type"] == "sqlite" else _get_duckdb(source_id)
    )
    try:
        tables = (
            _sqlite_tables(metadata_conn)
            if src["type"] == "sqlite"
            else _duckdb_tables(metadata_conn)
        )
        safe_table = (
            allow_identifier(table, tables, "table")
            if src["type"] == "sqlite"
            else _quote_duckdb_object(table, tables)
        )
        schema = (
            _sqlite_schema(metadata_conn, safe_table)
            if src["type"] == "sqlite"
            else _duckdb_schema(metadata_conn, table)
        )
        allowed_columns = {column["name"] for column in schema}
    finally:
        metadata_conn.close()

    try:
        filter_dict = json.loads(filters)
    except json.JSONDecodeError as error:
        raise ExplorerSqlError("Filters must be a JSON object.") from error
    if not isinstance(filter_dict, dict):
        raise ExplorerSqlError("Filters must be a JSON object.")
    window_definition = get_comparison_window(window)
    time_column = resolve_time_column(allowed_columns)
    window_column = time_column[0] if time_column else None
    window_grain = time_column[1] if time_column else None
    window_supported = (
        src["type"] == "duckdb"
        and src["layer"] in {"silver", "gold", "serving", "ml"}
        and window_column is not None
    )
    if window != "total" and not window_supported:
        raise HTTPException(
            422,
            "Comparison bands are available only for promoted date-capable tables.",
        )

    safe_sort_dir = "ASC" if sort_dir.lower() != "desc" else "DESC"
    offset = (page - 1) * page_size

    # Build WHERE clause
    where_parts, params = [], []
    for col, val in filter_dict.items():
        if val not in (None, "", []):
            safe_column = allow_identifier(col, allowed_columns, "column")
            if isinstance(val, list):
                placeholders = ",".join(["?" if src["type"]=="sqlite" else "$"+str(i+len(params)+1) for i, _ in enumerate(val)])
                where_parts.append(f"{safe_column} IN ({placeholders})")
                params.extend(val)
            else:
                ph = "?" if src["type"] == "sqlite" else f"${len(params)+1}"
                where_parts.append(f"{safe_column} = {ph}")
                params.append(val)

    where_clause  = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    safe_sort_col = (
        allow_identifier(sort_col, allowed_columns, "column") if sort_col else None
    )
    order_clause = f"ORDER BY {safe_sort_col} {safe_sort_dir}" if safe_sort_col else ""

    try:
        if src["type"] == "sqlite":
            conn = _get_sqlite(source_id)
            total = conn.execute(f"SELECT COUNT(*) FROM {safe_table} {where_clause}", params).fetchone()[0]
            rows  = conn.execute(
                f"SELECT * FROM {safe_table} {where_clause} {order_clause} LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()
            columns = [
                d[0]
                for d in conn.execute(f"SELECT * FROM {safe_table} LIMIT 0").description
            ]
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
                            safe_column = allow_identifier(col, allowed_columns, "column")
                            wp2.append(f"{safe_column} IN ({phs})")
                            params2.extend(val)
                        else:
                            safe_column = allow_identifier(col, allowed_columns, "column")
                            wp2.append(f"{safe_column} = ${len(params2)+1}")
                            params2.append(val)
                if window != "total" and window_column:
                    if window_grain == "date":
                        start_value = window_definition.start_date.isoformat()
                        end_value = window_definition.end_date.isoformat()
                    else:
                        start_value = (
                            window_definition.start_date.year * 100
                            + window_definition.start_date.month
                        )
                        end_value = (
                            window_definition.end_date.year * 100
                            + window_definition.end_date.month
                        )
                    safe_window_column = allow_identifier(
                        window_column, allowed_columns, "column"
                    )
                    wp2.append(
                        f"{safe_window_column} BETWEEN "
                        f"${len(params2)+1} AND ${len(params2)+2}"
                    )
                    params2.extend([start_value, end_value])
                where_clause = f"WHERE {' AND '.join(wp2)}"
                params = params2
            elif window != "total" and window_column:
                safe_window_column = allow_identifier(
                    window_column, allowed_columns, "column"
                )
                if window_grain == "date":
                    params = [
                        window_definition.start_date.isoformat(),
                        window_definition.end_date.isoformat(),
                    ]
                else:
                    params = [
                        window_definition.start_date.year * 100
                        + window_definition.start_date.month,
                        window_definition.end_date.year * 100
                        + window_definition.end_date.month,
                    ]
                where_clause = (
                    f"WHERE {safe_window_column} BETWEEN $1 AND $2"
                )

            total_rel = conn.execute(
                f"SELECT COUNT(*) FROM {safe_table} {where_clause}", params
            )
            total     = total_rel.fetchone()[0]
            rel = conn.execute(
                f"SELECT * FROM {safe_table} {where_clause} {order_clause} "
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
            "window": window,
            "window_supported": window_supported,
        }
    except ExplorerSqlError as error:
        raise HTTPException(400, str(error)) from error
    except Exception as error:
        raise HTTPException(400, "Data request could not be completed.") from error


@app.get("/explorer/api/distinct/{source_id}/{table}/{col}")
def get_distinct(source_id: str, table: str, col: str, limit: int = 200):
    src = _discover_sources().get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    try:
        safe_limit = clamp_limit(limit, 500)
        if src["type"] == "sqlite":
            conn = _get_sqlite(source_id)
            try:
                tables = _sqlite_tables(conn)
                safe_table = allow_identifier(table, tables, "table")
                columns = {
                    item["name"] for item in _sqlite_schema(conn, safe_table)
                }
                safe_column = allow_identifier(col, columns, "column")
                sql = (
                    f"SELECT DISTINCT {safe_column} FROM {safe_table} "
                    f"WHERE {safe_column} IS NOT NULL "
                    f"ORDER BY {safe_column} LIMIT {safe_limit}"
                )
                rows = conn.execute(sql).fetchall()
                values = [r[0] for r in rows]
            finally:
                conn.close()
        else:
            conn = _get_duckdb(source_id)
            try:
                tables = _duckdb_tables(conn)
                safe_table = _quote_duckdb_object(table, tables)
                columns = {
                    item["name"] for item in _duckdb_schema(conn, table)
                }
                safe_column = allow_identifier(col, columns, "column")
                sql = (
                    f"SELECT DISTINCT {safe_column} FROM {safe_table} "
                    f"WHERE {safe_column} IS NOT NULL "
                    f"ORDER BY {safe_column} LIMIT {safe_limit}"
                )
                rows = conn.execute(sql).fetchall()
                values = [r[0] for r in rows]
            finally:
                conn.close()
        return {"column": col, "values": values, "count": len(values)}
    except ExplorerSqlError as error:
        raise HTTPException(400, str(error)) from error
    except Exception as error:
        raise HTTPException(400, "Distinct values could not be loaded.") from error


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=50_000)
    limit: int = Field(default=500, ge=1)


@app.post("/explorer/api/query/{source_id}")
def run_query(source_id: str, req: QueryRequest):
    src = _discover_sources().get(source_id)
    if not src:
        raise HTTPException(404, "Source not found")
    try:
        if src["type"] == "sqlite":
            conn = _get_sqlite(source_id)
            try:
                parsed = parse_read_only_sql(
                    req.sql,
                    _sqlite_tables(conn),
                    limit=req.limit,
                    maximum_limit=MAX_QUERY_LIMIT,
                )
                cols, rows = _execute_sqlite_query(conn, parsed.sql)
            finally:
                conn.close()
        else:
            conn = _get_duckdb(source_id)
            try:
                parsed = parse_read_only_sql(
                    req.sql,
                    _duckdb_tables(conn),
                    limit=req.limit,
                    maximum_limit=MAX_QUERY_LIMIT,
                )
                cols, rows = _execute_duckdb_query(conn, parsed.sql)
            finally:
                conn.close()
        return {"columns": cols, "rows": rows, "row_count": len(rows)}
    except ExplorerSqlError as error:
        raise HTTPException(400, str(error)) from error
    except TimeoutError as error:
        raise HTTPException(408, "Query timed out.") from error
    except Exception as error:
        raise HTTPException(400, "Query could not be completed.") from error
