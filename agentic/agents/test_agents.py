"""
Step 13B — Agent Orchestrator Test
Run from project root: uv run python agentic/agents/test_agents.py

Tests:
  1. Router correctly classifies 5 sample queries
  2. Each agent successfully calls tools and synthesizes an answer
  3. End-to-end latency per agent
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentic.agents.orchestrator import ask
from agentic.agents.router import router_node, DOMAINS
from langchain_core.messages import HumanMessage


# ── Test queries — one per domain ─────────────────────────────────────────────
TEST_QUERIES = [
    {
        "question": "Which sites have CRITICAL bottlenecks and what is their capacity gap?",
        "expected_agent": "capacity",
    },
    {
        "question": "What is the ML-predicted yield for OTA tests? Which factors drive yield loss?",
        "expected_agent": "yield",
    },
    {
        "question": "Which equipment has HIGH or CRITICAL failure risk in the next 3 months?",
        "expected_agent": "maintenance",
    },
    {
        "question": "What is the demand forecast for the next 6 months and how accurate is it?",
        "expected_agent": "forecast",
    },
    {
        "question": "What is the P80 CapEx recommendation for OTA testers across all sites?",
        "expected_agent": "capex",
    },
]


def test_router():
    """Test that the router correctly classifies each query."""
    print("\n── Router Classification ──────────────────────────────────────")
    passed = 0
    for t in TEST_QUERIES:
        state = {
            "messages":     [HumanMessage(content=t["question"])],
            "agent":        "",
            "tool_results": [],
            "answer":       "",
            "error":        None,
        }
        result = router_node(state)
        got      = result["agent"]
        expected = t["expected_agent"]
        ok       = got == expected
        passed  += int(ok)
        mark     = "✓" if ok else "✗"
        print(f"  {mark} '{t['question'][:55]}...'")
        print(f"      Expected: {expected}  |  Got: {got}")
    print(f"\n  Router: {passed}/{len(TEST_QUERIES)} correct")
    return passed


def test_agents():
    """Run each query end-to-end through the full graph."""
    print("\n── End-to-End Agent Tests ─────────────────────────────────────")
    passed = 0
    for t in TEST_QUERIES:
        print(f"\n  [{t['expected_agent'].upper()} AGENT]")
        print(f"  Q: {t['question']}")
        t0 = time.time()
        try:
            result  = ask(t["question"])
            elapsed = time.time() - t0
            agent   = result["agent"]
            answer  = result["answer"]
            n_tools = len(result["tool_results"])
            error   = result["error"]

            if error:
                print(f"  ✗ ERROR: {error}")
            elif not answer:
                print(f"  ✗ No answer returned (agent={agent}, tools={n_tools})")
            else:
                print(f"  ✓ Agent={agent} | Tools called={n_tools} | {elapsed:.1f}s")
                # Print first 200 chars of answer
                preview = answer[:200].replace("\n", " ")
                print(f"  A: {preview}{'...' if len(answer) > 200 else ''}")
                passed += 1

        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ✗ EXCEPTION after {elapsed:.1f}s: {e}")

    print(f"\n  Agents: {passed}/{len(TEST_QUERIES)} succeeded")
    return passed


def main():
    print("=" * 60)
    print("STEP 13B — AGENT ORCHESTRATOR TEST")
    print("=" * 60)
    print("Note: Each query requires 2 LLM calls (tool selection + synthesis).")
    print("Expected time: 15–60s per query with llama3.1:8b on local Ollama.")

    router_passed = test_router()
    agent_passed  = test_agents()

    total = router_passed + agent_passed
    total_possible = len(TEST_QUERIES) * 2

    print("\n" + "=" * 60)
    print(f"TOTAL: {total}/{total_possible}")
    print("=" * 60)

    if agent_passed == len(TEST_QUERIES):
        print("\n✅ All agents working")
    else:
        print("\n⚠️  Some agents failed — check Ollama is running: ollama serve")
        print("   Then verify model: ollama run llama3.1:8b")


if __name__ == "__main__":
    main()
