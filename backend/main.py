"""
Step 13C — FastAPI Backend
==========================
Serves the chat API and static frontend files.

Endpoints:
  POST /api/chat          — full response (JSON)
  POST /api/chat/stream   — streaming SSE response
  GET  /api/health        — health check
  GET  /api/agents        — list available agents and their tools
  GET  /                  — serves frontend/index.html

Run:
  uv run python -m backend.main
  # or
  uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
"""

import json
import sys
import time
from pathlib import Path

# Project root on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from backend.models import (
    ChatRequest, ChatResponse, ToolResult, PipelineStep,
)
from agentic.agents.orchestrator import graph
from agentic.agents.domain_agents import AGENT_REGISTRY
from langchain_core.messages import HumanMessage

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Capacity Planning Digital Twin - Chat API",
    description="Multi-agent AI chatbot backed by DuckDB gold layer via MCP server.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
FRONTEND_DIR = PROJECT_ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _initial_state(question: str) -> dict:
    return {
        "messages":     [HumanMessage(content=question)],
        "agent":        "",
        "tool_results": [],
        "answer":       "",
        "error":        None,
    }


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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Frontend not found. Place files in frontend/"}


@app.get("/api/health")
async def health():
    return {
        "status":  "ok",
        "agents":  list(AGENT_REGISTRY.keys()),
        "version": "1.0.0",
    }


@app.get("/api/agents")
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


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Full synchronous chat — returns complete response as JSON."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    try:
        result = graph.invoke(_initial_state(req.question))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    agent        = result.get("agent", "unknown")
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


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """
    Streaming SSE endpoint.
    Emits newline-delimited JSON events:
      {"type": "pipeline", "data": {...}}   — pipeline step updates
      {"type": "token",    "data": "..."}   — answer token (word by word)
      {"type": "done",     "data": {...}}   — final metadata
      {"type": "error",    "data": "..."}   — on failure
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    def event_stream():
        try:
            # Emit pipeline steps as they happen via LangGraph stream
            agent_name   = "unknown"
            tool_results = []

            for chunk in graph.stream(
                _initial_state(req.question),
                stream_mode="updates",
            ):
                # chunk is {node_name: state_delta}
                for node, delta in chunk.items():

                    if node == "router":
                        agent_name = delta.get("agent", "unknown")
                        yield _sse({
                            "type": "pipeline",
                            "data": {
                                "step":   "router",
                                "detail": f"Query classified → {agent_name.upper()} agent",
                                "agent":  agent_name,
                            }
                        })

                    elif node in AGENT_REGISTRY:
                        raw     = delta.get("tool_results", [])
                        answer  = delta.get("answer", "")
                        tool_results = raw

                        # Emit tool execution steps
                        yield _sse({
                            "type": "pipeline",
                            "data": {
                                "step":   "tool_selection",
                                "detail": f"{agent_name.upper()} agent selected {len(raw)} tool(s)",
                                "agent":  agent_name,
                            }
                        })

                        for tr in raw:
                            r         = tr.get("result", {})
                            tool_name = tr.get("tool", "")
                            row_count = r.get("row_count", "?") if isinstance(r, dict) else "?"
                            cols      = r.get("columns", []) if isinstance(r, dict) else []
                            yield _sse({
                                "type": "pipeline",
                                "data": {
                                    "step":      "mcp_tool",
                                    "detail":    f"`{tool_name}` → DuckDB → {row_count} rows",
                                    "tool":      tool_name,
                                    "row_count": row_count,
                                    "columns":   cols[:8],   # first 8 cols
                                }
                            })

                        # Stream answer word by word
                        if answer:
                            yield _sse({
                                "type": "pipeline",
                                "data": {
                                    "step":   "synthesis",
                                    "detail": "Synthesizing answer via Ollama…",
                                }
                            })
                            words = answer.split(" ")
                            for i, word in enumerate(words):
                                sep = " " if i < len(words) - 1 else ""
                                yield _sse({"type": "token", "data": word + sep})

            # Final done event
            yield _sse({
                "type": "done",
                "data": {
                    "agent":        agent_name,
                    "tools_called": [tr.get("tool") for tr in tool_results],
                    "tool_count":   len(tool_results),
                }
            })

        except Exception as e:
            yield _sse({"type": "error", "data": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


# ── Dev entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(PROJECT_ROOT / "agentic"), str(PROJECT_ROOT / "backend")],
    )
