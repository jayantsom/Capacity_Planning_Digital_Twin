"""
LangGraph state schema.
Passed between every node in the graph.
"""

from typing import Annotated, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # Conversation history (add_messages merges lists automatically)
    messages:       Annotated[list, add_messages]

    # Set by RouterNode — which agent handles this query
    agent:          str                  # "capacity" | "yield" | "maintenance" | "forecast" | "capex" | "unknown"

    # Raw tool results collected during agent execution
    tool_results:   list[dict[str, Any]]

    # Final synthesized answer (streamed to caller)
    answer:         str

    # Optional: error message if something fails
    error:          str | None
