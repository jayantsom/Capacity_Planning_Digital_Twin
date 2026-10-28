"""Offline Operations Assistant API and SSE contract tests."""

import asyncio
import json
import threading
import time
from typing import ClassVar

from fastapi.testclient import TestClient

from operations_assistant.backend import main


class FakeAgent:
    description = "Offline fake"
    tools: ClassVar[dict] = {}

    async def arun(self, question: str, **_kwargs) -> dict:
        return {"answer": f"answer:{question}", "tool_results": []}

    async def astream(self, _question: str, **_kwargs):
        yield {
            "type": "tools",
            "tool_results": [{"tool": "safe_tool", "result": {"row_count": 1}}],
        }
        yield {"type": "token", "data": "<script>alert(1)</script>"}
        yield {"type": "token", "data": " streamed"}


async def _fake_route(_question: str) -> str:
    return "capacity"


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main, "route_question_async", _fake_route)
    monkeypatch.setitem(main.AGENT_REGISTRY, "capacity", FakeAgent())
    return TestClient(main.app)


def test_chat_uses_nonblocking_agent_contract(monkeypatch):
    client = _client(monkeypatch)
    response = client.post("/shared/api/yukti/chat", json={"question": "hello"})
    assert response.status_code == 200
    assert response.json()["answer"].endswith("User question: hello")


def test_page_context_controls_tool_permissions(monkeypatch):
    captured = {}

    class CapturingAgent(FakeAgent):
        async def arun(self, question: str, **kwargs) -> dict:
            captured["question"] = question
            captured["allowed_tools"] = kwargs["allowed_tools"]
            return {"answer": "ok", "tool_results": []}

    client = _client(monkeypatch)
    monkeypatch.setitem(main.AGENT_REGISTRY, "capacity", CapturingAgent())
    response = client.post(
        "/shared/api/yukti/chat",
        json={
            "question": "Write SQL for this table",
            "context": {
                "app_id": "data-explorer",
                "path": "/explorer/",
                "selected_table": "srv_vw_capacity_summary",
                "filters": {"site": "S1", "not_allowed": "ignored"},
            },
        },
    )
    assert response.status_code == 200
    assert "run_query" in captured["allowed_tools"]
    assert "get_capex_scenarios" not in captured["allowed_tools"]
    assert "not_allowed" not in captured["question"]


def test_page_context_rejects_a_mismatched_path(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/shared/api/yukti/chat",
        json={
            "question": "hello",
            "context": {
                "app_id": "data-explorer",
                "path": "/decision-intelligence/",
            },
        },
    )
    assert response.status_code == 422


def test_sse_has_immediate_event_and_real_model_chunks(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/shared/api/yukti/chat/stream",
        json={"question": "hello"},
    )
    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events[0]["type"] == "accepted"
    tokens = [event["data"] for event in events if event["type"] == "token"]
    assert tokens == ["<script>alert(1)</script>", " streamed"]
    assert events[-1]["type"] == "done"


def test_health_is_degraded_without_leaking_details(monkeypatch):
    async def fake_health():
        return {
            "status": "degraded",
            "components": {
                "api": "ok",
                "database": "unavailable",
                "schema": "unavailable",
                "ollama": "unavailable",
                "model": "unavailable",
            },
            "version": "test",
        }, False

    monkeypatch.setattr(main, "_health_payload", fake_health)
    client = TestClient(main.app)
    health = client.get("/shared/api/yukti/health")
    ready = client.get("/shared/api/yukti/ready")
    assert health.status_code == 200
    assert ready.status_code == 503
    assert "path" not in health.text.lower()
    assert "exception" not in health.text.lower()


def test_cors_allows_localhost_but_not_remote_origin(monkeypatch):
    client = _client(monkeypatch)
    local = client.options(
        "/shared/api/yukti/chat",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "POST",
        },
    )
    remote = client.options(
        "/shared/api/yukti/chat",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert local.headers["access-control-allow-origin"] == "http://localhost:8000"
    assert "access-control-allow-origin" not in remote.headers


def test_client_errors_are_sanitized(monkeypatch):
    class BrokenAgent(FakeAgent):
        async def arun(self, _question: str, **_kwargs) -> dict:
            raise RuntimeError("C:\\secret\\database.duckdb password=hidden")

    client = _client(monkeypatch)
    monkeypatch.setitem(main.AGENT_REGISTRY, "capacity", BrokenAgent())
    response = client.post("/shared/api/yukti/chat", json={"question": "hello"})
    assert response.status_code == 503
    assert "secret" not in response.text
    assert "password" not in response.text
    assert "Reference:" in response.text


def test_health_stays_responsive_during_slow_chat(monkeypatch):
    started = threading.Event()

    class SlowAgent(FakeAgent):
        async def arun(self, _question: str, **_kwargs) -> dict:
            started.set()
            await asyncio.sleep(0.25)
            return {"answer": "done", "tool_results": []}

    async def fake_health():
        return {
            "status": "ready",
            "components": {"api": "ok"},
            "version": "test",
        }, True

    client = _client(monkeypatch)
    monkeypatch.setitem(main.AGENT_REGISTRY, "capacity", SlowAgent())
    monkeypatch.setattr(main, "_health_payload", fake_health)
    worker = threading.Thread(
        target=lambda: client.post(
            "/shared/api/yukti/chat",
            json={"question": "slow"},
        ),
        daemon=True,
    )
    worker.start()
    assert started.wait(timeout=1)

    before = time.monotonic()
    response = client.get("/shared/api/yukti/health")
    elapsed = time.monotonic() - before
    worker.join(timeout=1)

    assert response.status_code == 200
    assert elapsed < 0.2


def test_chat_timeout_is_sanitized(monkeypatch):
    class SlowAgent(FakeAgent):
        async def arun(self, _question: str, **_kwargs) -> dict:
            await asyncio.sleep(1)
            return {"answer": "late", "tool_results": []}

    client = _client(monkeypatch)
    monkeypatch.setitem(main.AGENT_REGISTRY, "capacity", SlowAgent())
    monkeypatch.setattr(main, "AGENT_TIMEOUT_SECONDS", 0.01)
    response = client.post("/shared/api/yukti/chat", json={"question": "slow"})
    assert response.status_code == 504
    assert response.json()["detail"] == "The model request timed out."
