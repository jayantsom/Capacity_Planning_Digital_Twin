"""
Base Agent
==========
All 5 domain agents inherit from BaseAgent.
Handles: tool selection → tool execution → LLM synthesis → streaming answer.
"""

import json
from typing import AsyncIterator, Iterator

from langchain_core.messages import AIMessage

from agentic.agents.config import get_llm
from agentic.agents.state import AgentState


class BaseAgent:
    """
    Base class for all domain agents.

    Subclasses define:
      - name:           Agent identifier string
      - description:    What this agent handles
      - tools:          Dict of tool_name → callable
      - system_prompt:  Domain-specific system prompt
    """

    name:          str = "base"
    description:   str = ""
    tools:         dict = {}
    system_prompt: str = ""

    # ── Tool selection prompt ─────────────────────────────────────────────────

    TOOL_SELECTION_PROMPT = """You are a {name} analyst for a manufacturing capacity planning system.

{system_prompt}

Available tools:
{tool_list}

User question: {question}

Decide which tool(s) to call to answer this question.
Respond ONLY with a JSON array of tool calls:
[
  {{"tool": "<tool_name>", "args": {{<arg_name>: <value>, ...}}}},
  ...
]

Rules:
- Only use tools from the list above.
- Include only the args that are relevant — omit optional args you don't need.
- For month values use integer yyyymm format (e.g. 202301 for January 2023).
- If you need schema info first, call get_schema or list_tables.
- Return an empty array [] ONLY if no tool can help.
"""

    # ── Synthesis prompt ──────────────────────────────────────────────────────

    SYNTHESIS_PROMPT = """You are a {name} analyst for a manufacturing capacity planning system.

{system_prompt}

The user asked: {question}

You called the following tools and received these results:
{tool_results}

Write a clear, concise answer to the user's question based on the tool results.
- Use specific numbers from the data.
- Highlight the most important findings first.
- If the data shows a problem (bottleneck, high risk, low yield), flag it clearly.
- Keep the response focused — avoid repeating all the raw data.
- Use bullet points for lists of findings.
"""

    def _get_question(self, state: AgentState) -> str:
        for msg in reversed(state.get("messages", [])):
            if hasattr(msg, "type") and msg.type == "human":
                return msg.content
            if isinstance(msg, dict) and msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    def _build_tool_list(self) -> str:
        lines = []
        for name, fn in self.tools.items():
            doc = (fn.__doc__ or "").strip().split("\n")[0]
            lines.append(f"- {name}: {doc}")
        return "\n".join(lines)

    def _select_tools(self, question: str) -> list[dict]:
        """Ask the LLM which tools to call and with what args."""
        import re

        prompt = self.TOOL_SELECTION_PROMPT.format(
            name=self.name,
            system_prompt=self.system_prompt,
            tool_list=self._build_tool_list(),
            question=question,
        )
        llm = get_llm(streaming=False)
        try:
            response = llm.invoke(prompt)
            text = response.content if hasattr(response, "content") else str(response)

            # Extract JSON array — handle markdown code fences
            text = re.sub(r"```(?:json)?", "", text).strip()
            match = re.search(r'\[.*?\]', text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return []

    def _execute_tools(self, tool_calls: list[dict]) -> list[dict]:
        """Execute each selected tool and collect results."""
        results = []
        for call in tool_calls:
            tool_name = call.get("tool", "")
            args      = call.get("args", {})

            if tool_name not in self.tools:
                results.append({"tool": tool_name, "error": f"Unknown tool: {tool_name}"})
                continue

            try:
                result = self.tools[tool_name](**args)
                results.append({"tool": tool_name, "result": result})
            except Exception as e:
                results.append({"tool": tool_name, "error": str(e)})

        return results

    def _synthesize(self, question: str, tool_results: list[dict]) -> str:
        """Ask the LLM to synthesize tool results into a human answer."""
        # Truncate large result sets to avoid context overflow
        truncated = []
        for tr in tool_results:
            r = tr.get("result", tr.get("error", {}))
            rows = r.get("rows", []) if isinstance(r, dict) else []
            if len(rows) > 50:
                r = {**r, "rows": rows[:50],
                     "note": f"Showing first 50 of {len(rows)} rows"}
            truncated.append({"tool": tr["tool"],
                               "result": r if "result" in tr else tr.get("error")})

        prompt = self.SYNTHESIS_PROMPT.format(
            name=self.name,
            system_prompt=self.system_prompt,
            question=question,
            tool_results=json.dumps(truncated, indent=2, default=str),
        )
        llm = get_llm(streaming=False)
        response = llm.invoke(prompt)
        return response.content if hasattr(response, "content") else str(response)

    def run(self, state: AgentState) -> AgentState:
        """
        Synchronous node function called by LangGraph.
        Select tools → execute → synthesize → return updated state.
        """
        question = self._get_question(state)
        if not question:
            return {**state, "answer": "I couldn't find your question. Please try again.",
                    "tool_results": []}

        tool_calls   = self._select_tools(question)
        tool_results = self._execute_tools(tool_calls)
        answer       = self._synthesize(question, tool_results)

        return {
            **state,
            "tool_results": tool_results,
            "answer": answer,
            "messages": state["messages"] + [AIMessage(content=answer)],
        }
