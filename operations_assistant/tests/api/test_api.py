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

    async def arun(self, question: str) -> dict:
        return {"answer": f"answer:{question}", "tool_results": []}

    async def astream(self, _question: str):
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
    response = client.post("/operations-assistant/api/chat", json={"question": "hello"})
    assert response.status_code == 200
    assert response.json()["answer"] == "answer:hello"


def test_sse_has_immediate_event_and_real_model_chunks(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/operations-assistant/api/chat/stream",
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
    health = client.get("/operations-assistant/api/health")
    ready = client.get("/operations-assistant/api/ready")
    assert health.status_code == 200
    assert ready.status_code == 503
    assert "path" not in health.text.lower()
    assert "exception" not in health.text.lower()


def test_cors_allows_localhost_but_not_remote_origin(monkeypatch):
    client = _client(monkeypatch)
    local = client.options(
        "/operations-assistant/api/chat",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "POST",
        },
    )
    remote = client.options(
        "/operations-assistant/api/chat",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert local.headers["access-control-allow-origin"] == "http://localhost:8000"
    assert "access-control-allow-origin" not in remote.headers


def test_client_errors_are_sanitized(monkeypatch):
    class BrokenAgent(FakeAgent):
        async def arun(self, _question: str) -> dict:
            raise RuntimeError("C:\\secret\\database.duckdb password=hidden")

    client = _client(monkeypatch)
    monkeypatch.setitem(main.AGENT_REGISTRY, "capacity", BrokenAgent())
    response = client.post("/operations-assistant/api/chat", json={"question": "hello"})
    assert response.status_code == 503
    assert "secret" not in response.text
    assert "password" not in response.text
    assert "Reference:" in response.text


def test_health_stays_responsive_during_slow_chat(monkeypatch):
    started = threading.Event()

    class SlowAgent(FakeAgent):
        async def arun(self, _question: str) -> dict:
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
            "/operations-assistant/api/chat",
            json={"question": "slow"},
        ),
        daemon=True,
    )
    worker.start()
    assert started.wait(timeout=1)

    before = time.monotonic()
    response = client.get("/operations-assistant/api/health")
    elapsed = time.monotonic() - before
    worker.join(timeout=1)

    assert response.status_code == 200
    assert elapsed < 0.2


def test_chat_timeout_is_sanitized(monkeypatch):
    class SlowAgent(FakeAgent):
        async def arun(self, _question: str) -> dict:
            await asyncio.sleep(1)
            return {"answer": "late", "tool_results": []}

    client = _client(monkeypatch)
    monkeypatch.setitem(main.AGENT_REGISTRY, "capacity", SlowAgent())
    monkeypatch.setattr(main, "AGENT_TIMEOUT_SECONDS", 0.01)
    response = client.post("/operations-assistant/api/chat", json={"question": "slow"})
    assert response.status_code == 504
    assert response.json()["detail"] == "The model request timed out."
