"""
Router Node
===========
Classifies the user's query into one of 5 domains and sets state["agent"].
Uses a zero-shot prompt with llama3.1:8b — no examples needed as the
domain descriptions are distinct enough for reliable classification.
"""

from operations_assistant.agentic.agents.config import get_router_llm
from operations_assistant.agentic.agents.contracts import RouterDecision
from operations_assistant.agentic.agents.state import AgentState

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


def _fallback_domain(question: str) -> str:
    """Choose a deterministic safe route when structured model output fails."""
    lowered = question.lower()
    keywords = {
        "yield": ("yield", "shap", "first-pass"),
        "maintenance": ("maintenance", "failure", "oee", "repair"),
        "forecast": ("forecast", "future demand", "mape"),
        "capex": ("capex", "capital", "investment", "p80", "p95"),
    }
    for domain, terms in keywords.items():
        if any(term in lowered for term in terms):
            return domain
    return "capacity"


def _prompt(question: str) -> str:
    domain_list = "\n".join(
        f'- "{name}": {desc}' for name, desc in DOMAINS.items()
    )
    return ROUTER_PROMPT.format(domain_list=domain_list, question=question)


def route_question(question: str) -> str:
    """Route through a validated structured-output contract."""
    if not question:
        return "capacity"
    try:
        router = get_router_llm().with_structured_output(RouterDecision)
        return router.invoke(_prompt(question)).domain
    except Exception:  # noqa: BLE001 - routing always has a deterministic fallback
        return _fallback_domain(question)


async def route_question_async(question: str) -> str:
    """Asynchronously route without blocking FastAPI's event loop."""
    if not question:
        return "capacity"
    try:
        router = get_router_llm().with_structured_output(RouterDecision)
        decision = await router.ainvoke(_prompt(question))
        return decision.domain
    except Exception:  # noqa: BLE001 - routing always has a deterministic fallback
        return _fallback_domain(question)


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
        return {"agent": "capacity", "tool_results": [], "error": None}

    return {
        "agent": route_question(question),
        "tool_results": [],
        "error": None,
    }


def route_to_agent(state: AgentState) -> str:
    """
    LangGraph conditional edge function.
    Returns the node name to route to based on state["agent"].
    """
    return state.get("agent", "capacity")
