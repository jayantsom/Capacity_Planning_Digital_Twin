"""
Base Agent
==========
All 5 domain agents inherit from BaseAgent.
Handles: tool selection → tool execution → LLM synthesis → streaming answer.
"""

import asyncio
import inspect
import json
import re
from collections.abc import AsyncIterator
from typing import Any, ClassVar

from langchain_core.messages import AIMessage
from pydantic import TypeAdapter, ValidationError

from operations_assistant.agentic.agents.config import get_llm
from operations_assistant.agentic.agents.contracts import ToolCallContract, ToolPlan
from operations_assistant.agentic.agents.state import AgentState


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
    tools:         ClassVar[dict] = {}
    system_prompt: str = ""

    # ── Tool selection prompt ─────────────────────────────────────────────────

    TOOL_SELECTION_PROMPT = """You are a {name} analyst for a manufacturing capacity planning system.

{system_prompt}

Available tools:
{tool_list}

User question: {question}

Decide which tool(s) to call using the supplied structured-output contract.

Rules:
- Only use tools from the list above.
- Include only the args that are relevant — omit optional args you don't need.
- For month values use integer yyyymm format (e.g. 202301 for January 2023).
- If you need schema info first, call get_schema or list_tables.
- Return an empty calls list ONLY if no tool can help.
"""

    # ── Synthesis prompt ──────────────────────────────────────────────────────

    SYNTHESIS_PROMPT = """You are a {name} analyst for a manufacturing capacity planning system.

{system_prompt}

The user asked: {question}

You called the following tools and received these results:
{tool_results}

Write a clear, concise answer to the user's question based on the tool results.
- Write the COMPLETE answer. Do not truncate or summarize prematurely.
- Use specific numbers from the data.
- Highlight the most important findings first.
- If the data shows a problem (bottleneck, high risk, low yield), flag it clearly.
- Keep the response focused — avoid repeating all the raw data.
- If listing items, include all of them.
- Use bullet points for lists of findings.
"""

    def _get_question(self, state: AgentState) -> str:
        for msg in reversed(state.get("messages", [])):
            if hasattr(msg, "type") and msg.type == "human":
                return msg.content
            if isinstance(msg, dict) and msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    def _build_tool_list(self, allowed_tools: frozenset[str] | None = None) -> str:
        lines = []
        for name, fn in self.tools.items():
            if allowed_tools is not None and name not in allowed_tools:
                continue
            doc = (fn.__doc__ or "").strip().split("\n")[0]
            lines.append(f"- {name}: {doc}")
        return "\n".join(lines)

    def _tool_prompt(
        self,
        question: str,
        allowed_tools: frozenset[str] | None = None,
    ) -> str:
        """Build the bounded tool-selection prompt."""
        return self.TOOL_SELECTION_PROMPT.format(
            name=self.name,
            system_prompt=self.system_prompt,
            tool_list=self._build_tool_list(allowed_tools),
            question=question,
        )

    def _select_tools(self, question: str) -> list[ToolCallContract]:
        """Ask for schema-validated tool calls with a safe empty fallback."""
        try:
            planner = get_llm(streaming=False).with_structured_output(ToolPlan)
            return planner.invoke(self._tool_prompt(question)).calls
        except Exception:  # noqa: BLE001 - model failures use the safe no-tool fallback
            return []

    def _apply_trusted_bounds(
        self,
        question: str,
        tool_calls: list[ToolCallContract],
    ) -> list[ToolCallContract]:
        """Force application-selected month bounds into compatible tools."""
        match = re.search(r"month_from=(\d{6}) and month_to=(\d{6})", question)
        if not match:
            return tool_calls
        month_from, month_to = (int(value) for value in match.groups())
        bounded: list[ToolCallContract] = []
        for call in tool_calls:
            function = self.tools.get(call.tool)
            if function is None:
                bounded.append(call)
                continue
            parameters = inspect.signature(function).parameters
            args = dict(call.args)
            if "month_from" in parameters:
                args["month_from"] = month_from
            if "month_to" in parameters:
                args["month_to"] = month_to
            bounded.append(call.model_copy(update={"args": args}))
        return bounded

    async def _aselect_tools(
        self,
        question: str,
        allowed_tools: frozenset[str] | None = None,
    ) -> list[ToolCallContract]:
        """Select tools asynchronously so Ollama cannot block the API loop."""
        try:
            planner = get_llm(streaming=False).with_structured_output(ToolPlan)
            plan = await planner.ainvoke(self._tool_prompt(question, allowed_tools))
            return [
                call
                for call in plan.calls
                if allowed_tools is None or call.tool in allowed_tools
            ]
        except Exception:  # noqa: BLE001 - model failures use the safe no-tool fallback
            return []

    def _validated_args(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Validate argument names and values against the Python tool contract."""
        function = self.tools[tool_name]
        signature = inspect.signature(function)
        bound = signature.bind(**args)
        validated: dict[str, Any] = {}
        for name, value in bound.arguments.items():
            annotation = signature.parameters[name].annotation
            validated[name] = (
                value
                if annotation is inspect.Parameter.empty
                else TypeAdapter(annotation).validate_python(value)
            )
            if name in {"limit", "top_n"} and not 1 <= validated[name] <= 2_000:
                raise ValueError("Query bounds are outside the permitted range.")
        return validated

    def _execute_tools(
        self,
        tool_calls: list[ToolCallContract],
        allowed_tools: frozenset[str] | None = None,
    ) -> list[dict]:
        """Execute each selected tool and collect results."""
        results = []
        for call in tool_calls:
            tool_name = call.tool

            if (
                tool_name not in self.tools
                or (allowed_tools is not None and tool_name not in allowed_tools)
            ):
                results.append({"tool": tool_name, "error": "Unknown tool."})
                continue

            try:
                args = self._validated_args(tool_name, call.args)
                result = self.tools[tool_name](**args)
                results.append({"tool": tool_name, "result": result})
            except (TypeError, ValueError, ValidationError):
                results.append({"tool": tool_name, "error": "Invalid tool arguments."})
            except Exception:  # noqa: BLE001 - tool boundaries return sanitized errors
                results.append({"tool": tool_name, "error": "Tool execution failed."})

        return results

    async def _aexecute_tools(
        self,
        tool_calls: list[ToolCallContract],
        allowed_tools: frozenset[str] | None = None,
    ) -> list[dict]:
        """Run synchronous database tools on a worker thread."""
        return await asyncio.to_thread(self._execute_tools, tool_calls, allowed_tools)

    def _synthesis_prompt(self, question: str, tool_results: list[dict]) -> str:
        """Build a bounded synthesis prompt from structured tool results."""
        truncated = []
        for tool_result in tool_results:
            result = tool_result.get("result", tool_result.get("error", {}))
            rows = result.get("rows", []) if isinstance(result, dict) else []
            if len(rows) > 50:
                result = {
                    **result,
                    "rows": rows[:50],
                    "note": f"Showing first 50 of {len(rows)} rows",
                }
            truncated.append({
                "tool": tool_result["tool"],
                "result": result if "result" in tool_result else tool_result.get("error"),
            })
        return self.SYNTHESIS_PROMPT.format(
            name=self.name,
            system_prompt=self.system_prompt,
            question=question,
            tool_results=json.dumps(truncated, indent=2, default=str),
        )

    def _synthesize(self, question: str, tool_results: list[dict]) -> str:
        """Ask the LLM to synthesize tool results into a human answer."""
        llm = get_llm(streaming=False)
        response = llm.invoke(self._synthesis_prompt(question, tool_results))
        return response.content if hasattr(response, "content") else str(response)

    async def arun(
        self,
        question: str,
        *,
        allowed_tools: frozenset[str] | None = None,
    ) -> dict:
        """Run the complete agent through non-blocking Ollama and DB calls."""
        tool_calls = await self._aselect_tools(question, allowed_tools)
        tool_calls = self._apply_trusted_bounds(question, tool_calls)
        tool_results = await self._aexecute_tools(tool_calls, allowed_tools)
        response = await get_llm(streaming=False).ainvoke(
            self._synthesis_prompt(question, tool_results)
        )
        answer = response.content if hasattr(response, "content") else str(response)
        return {"answer": answer, "tool_results": tool_results}

    async def astream(
        self,
        question: str,
        *,
        allowed_tools: frozenset[str] | None = None,
    ) -> AsyncIterator[dict]:
        """Yield tool metadata followed by actual Ollama response chunks."""
        tool_calls = await self._aselect_tools(question, allowed_tools)
        tool_calls = self._apply_trusted_bounds(question, tool_calls)
        tool_results = await self._aexecute_tools(tool_calls, allowed_tools)
        yield {"type": "tools", "tool_results": tool_results}
        async for chunk in get_llm(streaming=True).astream(
            self._synthesis_prompt(question, tool_results)
        ):
            content = chunk.content if hasattr(chunk, "content") else str(chunk)
            if isinstance(content, str) and content:
                yield {"type": "token", "data": content}

    def run(self, state: AgentState) -> AgentState:
        """
        Synchronous node function called by LangGraph.
        Select tools → execute → synthesize → return updated state.
        """
        question = self._get_question(state)
        if not question:
            return {
                "answer": "I couldn't find your question. Please try again.",
                "tool_results": [],
            }

        tool_calls   = self._apply_trusted_bounds(
            question, self._select_tools(question)
        )
        tool_results = self._execute_tools(tool_calls)
        answer       = self._synthesize(question, tool_results)

        return {
            "tool_results": tool_results,
            "answer": answer,
            # add_messages merges history; return only the newly produced message.
            "messages": [AIMessage(content=answer)],
        }
