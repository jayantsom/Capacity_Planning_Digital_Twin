"""
Step 13C — FastAPI Backend
==========================
Serves the chat API and static frontend files.

Endpoints:
  POST /operations-assistant/api/chat          — full response (JSON)
  POST /operations-assistant/api/chat/stream   — streaming SSE response
  GET  /operations-assistant/api/health        — health check
  GET  /operations-assistant/api/agents        — list available agents and their tools
"""

import asyncio
import ipaddress
import json
import logging
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from capacity_twin_core.comparison import get_comparison_window
from capacity_twin_core.runtime.database_paths import load_app_config
from operations_assistant.agentic.agents.domain_agents import AGENT_REGISTRY
from operations_assistant.agentic.agents.router import route_question_async
from operations_assistant.agentic.mcp_server.db import get_conn
from operations_assistant.backend.models import (
    ChatRequest,
    ChatResponse,
    PipelineStep,
    ToolResult,
)

APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_CONFIG = load_app_config("operations_assistant")
logger = logging.getLogger(__name__)


def _is_loopback_host(value: str) -> bool:
    """Return whether a host name or IP is local-only."""
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _validated_origins() -> list[str]:
    """Reject wildcard or non-loopback browser origins at startup."""
    origins = APP_CONFIG.get("server", {}).get("allowed_origins", [])
    if not origins or "*" in origins:
        raise RuntimeError("Operations Assistant requires explicit localhost CORS origins.")
    for origin in origins:
        parsed = urlparse(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or not _is_loopback_host(parsed.hostname)
        ):
            raise RuntimeError("Operations Assistant CORS origins must be explicit and localhost-only.")
    return origins


ALLOWED_ORIGINS = _validated_origins()
AGENT_TIMEOUT_SECONDS = float(APP_CONFIG.get("agentic", {}).get("timeout_seconds", 120))
MODEL_SEMAPHORE = asyncio.Semaphore(1)

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Operations Assistant API",
    description="Multi-agent AI chatbot backed by DuckDB gold layer via MCP server.",
    version="1.0.0",
    docs_url="/operations-assistant/api/docs",
    redoc_url="/operations-assistant/api/redoc",
    openapi_url="/operations-assistant/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Serve frontend static files
FRONTEND_DIR = APP_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount(
        "/operations-assistant/static",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="operations_assistant_static",
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_tool_results(raw: list[dict]) -> list[ToolResult]:
    results = []
    for tr in raw:
        r = tr.get("result", {})
        if isinstance(r, dict):
            results.append(ToolResult(
                tool=tr.get("tool", ""),
                row_count=r.get("row_count"),
                columns=r.get("columns", []),
                error=r.get("error") or tr.get("error"),
            ))
        else:
            results.append(ToolResult(
                tool=tr.get("tool", ""),
                error=tr.get("error"),
            ))
    return results


def _build_pipeline_steps(agent: str, tool_results: list[dict]) -> list[PipelineStep]:
    steps = [
        PipelineStep(step="router",
                     detail=f"Query classified → {agent.upper()} agent"),
        PipelineStep(step="tool_selection",
                     detail=f"LLM ({agent.upper()} agent) selected {len(tool_results)} tool(s) via Ollama"),
    ]
    for tr in tool_results:
        r         = tr.get("result", {})
        tool_name = tr.get("tool", "unknown")
        row_count = r.get("row_count", "?") if isinstance(r, dict) else "?"
        steps.append(PipelineStep(
            step="mcp_tool",
            detail=f"MCP tool `{tool_name}` → DuckDB → {row_count} rows",
        ))
    steps.append(PipelineStep(
        step="synthesis",
        detail="LLM synthesized final answer via Ollama",
    ))
    return steps


async def _database_health() -> tuple[tuple[bool, bool], tuple[bool, bool]]:
    """Check Serving and ML publications off the event loop."""
    def inspect_database(database: str, prefixes: tuple[str, ...]) -> tuple[bool, bool]:
        conn = get_conn(database)
        try:
            conn.execute("SELECT 1").fetchone()
            predicates = " OR ".join(
                "table_name LIKE ?" for _ in prefixes
            )
            count = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema='main' "
                f"AND ({predicates})",
                [f"{prefix}%" for prefix in prefixes],
            ).fetchone()[0]
            return True, count > 0
        finally:
            conn.close()

    def safe_inspect(database: str, prefixes: tuple[str, ...]) -> tuple[bool, bool]:
        try:
            return inspect_database(database, prefixes)
        except Exception:  # noqa: BLE001 - each component degrades independently
            return False, False

    serving, ml = await asyncio.gather(
        asyncio.to_thread(safe_inspect, "serving", ("gold_", "srv_vw_")),
        asyncio.to_thread(safe_inspect, "ml", ("gold_",)),
    )
    return serving, ml


async def _ollama_health() -> tuple[bool, bool]:
    """Check Ollama and its configured model without leaking remote details."""
    cfg = APP_CONFIG.get("agentic", {})
    url = cfg.get("ollama_base_url", "http://localhost:11434").rstrip("/")
    model = cfg.get("default_model", "llama3.1:8b")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{url}/api/tags")
            response.raise_for_status()
            names = {item.get("name") for item in response.json().get("models", [])}
            return True, model in names
    except Exception:  # noqa: BLE001 - health checks degrade without leaking details
        return False, False


async def _health_payload() -> tuple[dict, bool]:
    database_health, (ollama_ok, model_ok) = await asyncio.gather(
        _database_health(), _ollama_health()
    )
    (serving_ok, serving_schema_ok), (ml_ok, ml_schema_ok) = database_health
    database_ok = serving_ok and ml_ok
    schema_ok = serving_schema_ok and ml_schema_ok
    ready = database_ok and schema_ok and ollama_ok and model_ok
    return {
        "status": "ready" if ready else "degraded",
        "components": {
            "api": "ok",
            "database": "ok" if database_ok else "unavailable",
            "schema": "ok" if schema_ok else "unavailable",
            "serving_database": "ok" if serving_ok else "unavailable",
            "serving_schema": "ok" if serving_schema_ok else "unavailable",
            "ml_database": "ok" if ml_ok else "unavailable",
            "ml_schema": "ok" if ml_schema_ok else "unavailable",
            "ollama": "ok" if ollama_ok else "unavailable",
            "model": "ok" if model_ok else "unavailable",
        },
        "version": "1.1.0",
    }, ready


def _public_error(correlation_id: str) -> str:
    return f"Request could not be completed. Reference: {correlation_id}"


def _question_context(req: ChatRequest) -> tuple[str, dict]:
    """Add a trusted analytical-window instruction to the agent request."""
    if req.window_id == "total":
        return req.question, {
            "window_id": "total",
            "display_name": "Total",
            "start_date": None,
            "end_date": None,
        }
    window = get_comparison_window(req.window_id)
    metadata = window.as_dict()
    month_from = window.start_date.year * 100 + window.start_date.month
    month_to = window.end_date.year * 100 + window.end_date.month
    instruction = (
        "\n\nTrusted application context: analyze only dates from "
        f"{metadata['start_date']} through {metadata['end_date']} "
        f"for {metadata['display_name']}. For monthly tools, always pass "
        f"month_from={month_from} and month_to={month_to}. "
        "Do not combine data outside these bounds."
    )
    return req.question + instruction, metadata


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/operations-assistant/api/health")
async def health():
    payload, _ = await _health_payload()
    return payload


@app.get("/operations-assistant/api/ready")
async def readiness():
    payload, ready = await _health_payload()
    return JSONResponse(payload, status_code=200 if ready else 503)


@app.get("/operations-assistant/api/agents")
async def list_agents():
    return {
        "agents": [
            {
                "name":        name,
                "description": agent.description,
                "tools":       list(agent.tools.keys()),
            }
            for name, agent in AGENT_REGISTRY.items()
        ]
    }


@app.post("/operations-assistant/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Return a complete response without blocking the server event loop."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        contextual_question, window = _question_context(req)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    try:
        async with MODEL_SEMAPHORE:
            async with asyncio.timeout(AGENT_TIMEOUT_SECONDS):
                agent = await route_question_async(contextual_question)
                result = await AGENT_REGISTRY[agent].arun(contextual_question)
    except TimeoutError as error:
        raise HTTPException(status_code=504, detail="The model request timed out.") from error
    except Exception as error:
        correlation_id = uuid4().hex
        logger.exception("Chat failed correlation_id=%s", correlation_id)
        raise HTTPException(
            status_code=503,
            detail=_public_error(correlation_id),
        ) from error

    raw_tools    = result.get("tool_results", [])
    tool_results = _extract_tool_results(raw_tools)
    pipeline     = _build_pipeline_steps(agent, raw_tools)

    return ChatResponse(
        answer=result.get("answer", ""),
        agent=agent,
        tool_results=tool_results,
        pipeline_steps=pipeline,
        error=result.get("error"),
        window_id=window["window_id"],
        window_label=window["display_name"],
    )


@app.post("/operations-assistant/api/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """
    Streaming SSE endpoint.
    Emits newline-delimited JSON events:
      {"type": "pipeline", "data": {...}}   — pipeline step updates
      {"type": "token",    "data": "..."}   — actual Ollama stream chunk
      {"type": "done",     "data": {...}}   — final metadata
      {"type": "error",    "data": "..."}   — on failure
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    try:
        contextual_question, window = _question_context(req)
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    async def event_stream():
        agent_name = "unknown"
        tool_results: list[dict] = []
        try:
            # Send an immediate first event before any model or database work.
            yield _sse({"type": "accepted", "data": "Request accepted."})
            async with MODEL_SEMAPHORE:
                async with asyncio.timeout(AGENT_TIMEOUT_SECONDS):
                    agent_name = await route_question_async(contextual_question)
                    yield _sse({
                        "type": "pipeline",
                        "data": {
                            "step": "router",
                            "detail": f"Query classified → {agent_name.upper()} agent",
                            "agent": agent_name,
                        },
                    })

                    async for event in AGENT_REGISTRY[agent_name].astream(
                        contextual_question
                    ):
                        if await request.is_disconnected():
                            return
                        if event["type"] == "tools":
                            tool_results = event["tool_results"]
                            yield _sse({
                                "type": "pipeline",
                                "data": {
                                    "step": "tool_selection",
                                    "detail": (
                                        f"{agent_name.upper()} agent selected "
                                        f"{len(tool_results)} tool(s)"
                                    ),
                                    "agent": agent_name,
                                },
                            })
                            for tool_result in tool_results:
                                result = tool_result.get("result", {})
                                row_count = (
                                    result.get("row_count", "?")
                                    if isinstance(result, dict)
                                    else "?"
                                )
                                yield _sse({
                                    "type": "pipeline",
                                    "data": {
                                        "step": "mcp_tool",
                                        "detail": "Read-only data tool completed.",
                                        "tool": tool_result.get("tool", ""),
                                        "row_count": row_count,
                                    },
                                })
                            yield _sse({
                                "type": "pipeline",
                                "data": {
                                    "step": "synthesis",
                                    "detail": "Streaming response via Ollama…",
                                },
                            })
                        elif event["type"] == "token":
                            yield _sse(event)

            if await request.is_disconnected():
                return
            yield _sse({
                "type": "done",
                "data": {
                    "agent": agent_name,
                    "tools_called": [item.get("tool") for item in tool_results],
                    "tool_count": len(tool_results),
                    "window_id": window["window_id"],
                    "window_label": window["display_name"],
                },
            })

        except TimeoutError:
            yield _sse({"type": "error", "data": "The model request timed out."})
        except asyncio.CancelledError:
            raise
        except Exception:
            correlation_id = uuid4().hex
            logger.exception("Stream failed correlation_id=%s", correlation_id)
            yield _sse({
                "type": "error",
                "data": _public_error(correlation_id),
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
        },
    )


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
