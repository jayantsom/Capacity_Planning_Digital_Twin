# Domain Agents

Capacity Assistant preserves five domain agents:

| Agent | Scope |
|---|---|
| Capacity | Demand, supply, utilization, bottlenecks, routes, and equipment |
| Yield | Measured-yield predictions, explanations, and capacity impact |
| OEE degradation risk | Synthetic OEE-risk scores and trends |
| Forecast | Demand forecasts, horizons, temporal evaluation, and baselines |
| CapEx | Monte Carlo equipment scenarios and assumptions |

The router and agents use local `llama3.1:8b` through Ollama. The model may select tools and summarize returned evidence, but it must not invent operational numbers.

## State and routing

LangGraph carries message history, selected domain, tool results, answer, and internal error state. Nodes should return only newly produced messages when using the `add_messages` reducer.

Routing and tool arguments require schema-validated structured output with a safe fallback. Regex extraction may be retained only as a bounded compatibility fallback and must not silently convert every model error into a confident capacity answer.

## Response contract

- Cite the relevant run/data version in evidence.
- Distinguish actuals through 2026-10-31 from forecasts beginning 2026-11-01.
- Label all data as synthetic and Erivon as fictional.
- Describe OEE degradation risk honestly.
- Describe CapEx as simulation.
- Avoid model-quality or business-quality claims without holdout evidence.
- Degrade clearly when Ollama is offline while leaving Data Explorer usable.

Agent tests should use fake model responses and temporary data so routing, tools, API/SSE, cancellation, timeouts, and error sanitization do not require a live Ollama instance.
