"""Offline tests for message reducers and tool contracts."""

from typing import ClassVar

from langchain_core.messages import AIMessage, HumanMessage

from capacity_assistant.agentic.agents.base_agent import BaseAgent
from capacity_assistant.agentic.agents.contracts import ToolCallContract


class FakeAgent(BaseAgent):
    name = "fake"
    tools: ClassVar[dict] = {"echo": lambda value: {"value": value}}


def test_agent_returns_only_new_message(monkeypatch):
    agent = FakeAgent()
    monkeypatch.setattr(
        agent,
        "_select_tools",
        lambda _question: [],
    )
    monkeypatch.setattr(agent, "_synthesize", lambda _question, _results: "new answer")
    history = [HumanMessage(content="question"), AIMessage(content="old answer")]

    update = agent.run({
        "messages": history,
        "agent": "fake",
        "tool_results": [],
        "answer": "",
        "error": None,
    })

    assert len(update["messages"]) == 1
    assert update["messages"][0].content == "new answer"


def test_tool_contract_rejects_unknown_arguments():
    agent = FakeAgent()
    result = agent._execute_tools([
        ToolCallContract(tool="echo", args={"value": "ok", "unexpected": True})
    ])
    assert result == [{"tool": "echo", "error": "Invalid tool arguments."}]


def test_tool_contract_rejects_unknown_tool():
    agent = FakeAgent()
    result = agent._execute_tools([
        ToolCallContract(tool="not_registered", args={})
    ])
    assert result == [{"tool": "not_registered", "error": "Unknown tool."}]
