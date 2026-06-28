"""
Router Node
===========
Classifies the user's query into one of 5 domains and sets state["agent"].
Uses a zero-shot prompt with llama3.1:8b — no examples needed as the
domain descriptions are distinct enough for reliable classification.
"""

import json
import re

from agentic.agents.config import get_router_llm
from agentic.agents.state import AgentState

# ── Domain descriptions ───────────────────────────────────────────────────────
DOMAINS = {
    "capacity": (
        "Questions about production capacity, equipment utilization, supply vs demand, "
        "bottlenecks, capacity gaps, normal/maximum capacity, headroom, investment needs, "
        "excess capacity, or capacity planning."
    ),
    "yield": (
        "Questions about manufacturing yield rates, first-pass yield, yield predictions, "
        "yield loss drivers, SHAP feature importance, ML-adjusted capacity based on yield, "
        "or yield improvement."
    ),
    "maintenance": (
        "Questions about equipment maintenance, failure risk, predictive maintenance alerts, "
        "HIGH or CRITICAL risk equipment, OEE-based failure probability, or maintenance planning."
    ),
    "forecast": (
        "Questions about demand forecasting, future demand predictions, forecast accuracy, "
        "MAPE, Prophet or ensemble model forecasts, NPI product ramp, or planning horizon demand."
    ),
    "capex": (
        "Questions about capital expenditure, CapEx recommendations, Monte Carlo equipment "
        "quantity planning, P50/P80/P95 investment scenarios, equipment purchase decisions, "
        "or cost of new equipment."
    ),
}

ROUTER_PROMPT = """You are a routing assistant for a manufacturing capacity planning system.
Classify the user's question into exactly one of these domains:

{domain_list}

Respond with ONLY a JSON object in this exact format:
{{"domain": "<domain_name>", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}}

User question: {question}"""


def router_node(state: AgentState) -> AgentState:
    """
    Classify the latest user message and set state["agent"].
    Falls back to "capacity" if classification fails.
    """
    # Get latest user message
    messages = state.get("messages", [])
    question = ""
    for msg in reversed(messages):
        content = msg.content if hasattr(msg, "content") else str(msg)
        if hasattr(msg, "type") and msg.type == "human":
            question = content
            break
        elif isinstance(msg, dict) and msg.get("role") == "user":
            question = msg.get("content", "")
            break

    if not question:
        return {**state, "agent": "capacity", "error": None}

    # Build domain list for prompt
    domain_list = "\n".join(
        f'- "{name}": {desc}' for name, desc in DOMAINS.items()
    )

    prompt = ROUTER_PROMPT.format(
        domain_list=domain_list,
        question=question,
    )

    llm = get_router_llm()
    try:
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)

        # Extract JSON — handle cases where model wraps in markdown
        match = re.search(r'\{.*?\}', text, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            domain = parsed.get("domain", "capacity").lower()
            if domain not in DOMAINS:
                domain = "capacity"
        else:
            domain = "capacity"

    except Exception:
        domain = "capacity"   # safe fallback

    return {**state, "agent": domain, "tool_results": [], "error": None}


def route_to_agent(state: AgentState) -> str:
    """
    LangGraph conditional edge function.
    Returns the node name to route to based on state["agent"].
    """
    return state.get("agent", "capacity")
