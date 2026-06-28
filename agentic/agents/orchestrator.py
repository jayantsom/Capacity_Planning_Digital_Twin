"""
LangGraph Orchestrator
======================
Wires the RouterNode + 5 domain agent nodes into a compiled LangGraph.

Graph structure:
    START → router → [capacity | yield | maintenance | forecast | capex] → END

Usage:
    from agentic.agents.orchestrator import graph
    result = graph.invoke({"messages": [HumanMessage(content="...")]})
    print(result["answer"])
"""

from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END

from agentic.agents.state import AgentState
from agentic.agents.router import router_node, route_to_agent
from agentic.agents.domain_agents import AGENT_REGISTRY


# ── Build graph ───────────────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    # Router node
    builder.add_node("router", router_node)

    # One node per domain agent
    for agent_name, agent in AGENT_REGISTRY.items():
        builder.add_node(agent_name, agent.run)

    # Entry point
    builder.add_edge(START, "router")

    # Conditional routing: router → one of 5 agents
    builder.add_conditional_edges(
        "router",
        route_to_agent,
        {name: name for name in AGENT_REGISTRY},
    )

    # All agents go to END
    for agent_name in AGENT_REGISTRY:
        builder.add_edge(agent_name, END)

    return builder.compile()


# Compiled graph — import this in FastAPI and tests
graph = _build_graph()


# ── Convenience helpers ───────────────────────────────────────────────────────

def ask(question: str) -> dict:
    """
    Single-turn synchronous query.

    Args:
        question: Natural language question.

    Returns:
        {
          "answer":       str,
          "agent":        str,   # which agent handled it
          "tool_results": list,  # raw tool outputs
          "error":        str | None,
        }
    """
    result = graph.invoke({
        "messages":     [HumanMessage(content=question)],
        "agent":        "",
        "tool_results": [],
        "answer":       "",
        "error":        None,
    })
    return {
        "answer":       result.get("answer", ""),
        "agent":        result.get("agent", ""),
        "tool_results": result.get("tool_results", []),
        "error":        result.get("error"),
    }


def ask_stream(question: str):
    """
    Single-turn streaming query using LangGraph's stream().
    Yields state deltas — caller extracts the final answer.

    Usage:
        for chunk in ask_stream("What are the critical bottlenecks?"):
            if chunk.get("answer"):
                print(chunk["answer"], end="", flush=True)
    """
    for chunk in graph.stream(
        {
            "messages":     [HumanMessage(content=question)],
            "agent":        "",
            "tool_results": [],
            "answer":       "",
            "error":        None,
        },
        stream_mode="updates",
    ):
        yield chunk
