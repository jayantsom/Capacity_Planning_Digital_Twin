"""
Step 13C — FastAPI Backend
==========================
Serves the shared contextual Yukti API.

Endpoints:
  POST /shared/api/yukti/chat          - full response (JSON)
  POST /shared/api/yukti/chat/stream   - streaming SSE response
  GET  /shared/api/yukti/health        - health check
  GET  /shared/api/yukti/agents        - list available agents and their tools
"""

import asyncio
import ipaddress
import json
import logging
import re
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from capacity_twin_core.runtime.database_paths import load_app_config
from operations_assistant.agentic.agents.domain_agents import AGENT_REGISTRY
from operations_assistant.agentic.agents.router import route_question_async
from operations_assistant.agentic.mcp_server.db import get_conn
from operations_assistant.backend.models import (
    ChatRequest,
    ChatResponse,
    PageContext,
    PipelineStep,
    ToolResult,
)

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
    title="Yukti Shared API",
    description="Context-aware local assistant backed by governed read-only data.",
    version="1.0.0",
    docs_url="/shared/api/yukti/docs",
    redoc_url="/shared/api/yukti/redoc",
    openapi_url="/shared/api/yukti/openapi.json",
)
router = APIRouter()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

# Serve frontend static files
SCHEMA_TOOLS = frozenset(
    {"list_tables", "get_schema", "get_table_preview", "get_distinct_values"}
)
ANALYTICS_TOOLS = frozenset(
    {
        "get_capacity_summary",
        "get_bottleneck_analysis",
        "get_demand_vs_supply",
        "get_equipment_utilization",
        "get_yield_prediction",
        "get_yield_drivers",
        "get_ml_adjusted_capacity",
        "get_operational_performance",
        "get_maintenance_alerts",
        "get_failure_risk_trend",
        "get_demand_forecast",
        "get_forecast_accuracy",
        "get_capex_recommendation",
        "get_capex_scenarios",
        *SCHEMA_TOOLS,
    }
)
APP_TOOL_POLICY = {
    "data-explorer": frozenset({*SCHEMA_TOOLS, "run_query"}),
    "data-operations": SCHEMA_TOOLS,
    "documentation": frozenset(),
}
APP_PATHS = {
    "home": "/",
    "data-explorer": "/explorer/",
    "capacity-analysis": "/capacity-analysis/",
    "decision-intelligence": "/decision-intelligence/",
    "scenario-planning": "/scenario-planning/",
    "demand-supply-planning": "/demand-supply-planning/",
    "npi-ramp-planning": "/npi-ramp-planning/",
    "operations-flow": "/operations-flow/",
    "data-operations": "/data-operations/",
    "documentation": "/documentation/",
}
FILTER_ALLOWLIST = frozenset(
    {
        "site",
        "product",
        "test_type",
        "machine",
        "planning_version",
        "month_from",
        "month_to",
        "date_from",
        "date_to",
        "grain",
        "capacity_mode",
        "retest_type",
        "program",
        "operation",
        "resource",
        "layer",
    }
)
WORKFLOW_AGENT = {
    "demand": "forecast",
    "yield": "yield",
    "oee-risk": "maintenance",
    "oee-anomaly": "maintenance",
    "capex": "capex",
}


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
        asyncio.to_thread(safe_inspect, "serving", ("srv_",)),
        asyncio.to_thread(safe_inspect, "ml", ("ml_",)),
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


def _validated_context(context: PageContext) -> dict:
    expected_path = APP_PATHS[context.app_id]
    if context.app_id == "home":
        valid_path = context.path == "/"
    else:
        valid_path = context.path.startswith(expected_path)
    if not valid_path:
        raise HTTPException(status_code=422, detail="Page context does not match the app.")
    if context.selected_table and not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_.]{0,149}",
        context.selected_table,
    ):
        raise HTTPException(status_code=422, detail="Selected table is not valid.")
    filters = {
        key: value
        for key, value in list(context.filters.items())[:20]
        if key in FILTER_ALLOWLIST and value not in (None, "")
    }
    return {
        "app_id": context.app_id,
        "path": context.path,
        "view": context.view,
        "selected_table": context.selected_table,
        "filters": filters,
    }


def _contextual_request(req: ChatRequest) -> tuple[str, str, frozenset[str]]:
    context = _validated_context(req.context)
    agent = WORKFLOW_AGENT.get(str(context["view"]))
    if not agent:
        agent = {
            "capacity-analysis": "capacity",
            "scenario-planning": "capacity",
            "demand-supply-planning": "forecast",
            "npi-ramp-planning": "forecast",
            "operations-flow": "capacity",
        }.get(str(context["app_id"]))
    prompt = (
        "Validated current page context:\n"
        f"{json.dumps(context, sort_keys=True, default=str)}\n\n"
        "Use this context when it is relevant. Do not invent filters, tables, "
        "metrics, or results that are not returned by a tool. "
    )
    if context["app_id"] == "data-explorer":
        prompt += (
            "For data questions, inspect the published schema first when needed. "
            "Only generate or run bounded read-only SQL against allowlisted tables. "
        )
    prompt += f"\nUser question: {req.question}"
    allowed_tools = APP_TOOL_POLICY.get(str(context["app_id"]), ANALYTICS_TOOLS)
    return agent or "", prompt, allowed_tools


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/shared/api/yukti/health")
async def health():
    payload, _ = await _health_payload()
    return payload


@router.get("/shared/api/yukti/ready")
async def readiness():
    payload, ready = await _health_payload()
    return JSONResponse(payload, status_code=200 if ready else 503)


@router.get("/shared/api/yukti/agents")
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


@router.post("/shared/api/yukti/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Return a complete response without blocking the server event loop."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    contextual_agent, contextual_prompt, allowed_tools = _contextual_request(req)

    try:
        async with MODEL_SEMAPHORE:
            async with asyncio.timeout(AGENT_TIMEOUT_SECONDS):
                agent = contextual_agent or await route_question_async(req.question)
                result = await AGENT_REGISTRY[agent].arun(
                    contextual_prompt,
                    allowed_tools=allowed_tools,
                )
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
    )


@router.post("/shared/api/yukti/chat/stream")
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
    contextual_agent, contextual_prompt, allowed_tools = _contextual_request(req)
    async def event_stream():
        agent_name = "unknown"
        tool_results: list[dict] = []
        try:
            # Send an immediate first event before any model or database work.
            yield _sse({"type": "accepted", "data": "Request accepted."})
            async with MODEL_SEMAPHORE:
                async with asyncio.timeout(AGENT_TIMEOUT_SECONDS):
                    agent_name = (
                        contextual_agent or await route_question_async(req.question)
                    )
                    yield _sse({
                        "type": "pipeline",
                        "data": {
                            "step": "router",
                            "detail": f"Query classified → {agent_name.upper()} agent",
                            "agent": agent_name,
                        },
                    })

                    async for event in AGENT_REGISTRY[agent_name].astream(
                        contextual_prompt,
                        allowed_tools=allowed_tools,
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


app.include_router(router)
