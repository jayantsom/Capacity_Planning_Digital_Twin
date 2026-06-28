"""
MCP Server Smoke Test
Run from project root: uv run python agentic/mcp_server/test_server.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentic.mcp_server.tools.schema_tools import (
    list_tables, get_schema, get_table_preview, get_distinct_values
)
from agentic.mcp_server.tools.capacity_tools import (
    get_capacity_summary, get_bottleneck_analysis,
    get_demand_vs_supply, get_equipment_utilization
)
from agentic.mcp_server.tools.yield_tools import (
    get_yield_prediction, get_yield_drivers, get_ml_adjusted_capacity
)
from agentic.mcp_server.tools.maintenance_tools import (
    get_maintenance_alerts, get_failure_risk_trend
)
from agentic.mcp_server.tools.forecast_tools import (
    get_demand_forecast, get_forecast_accuracy
)
from agentic.mcp_server.tools.capex_tools import (
    get_capex_recommendation, get_capex_scenarios
)
from agentic.mcp_server.tools.query_tool import run_query


def check(name: str, result: dict, expect_error: bool = False) -> bool:
    has_error = "error" in result
    if expect_error:
        if has_error:
            print(f"  ✓ {name}: correctly blocked — {result['error']}")
            return True
        else:
            print(f"  ✗ {name}: should have been blocked but wasn't")
            return False
    if has_error:
        print(f"  ✗ {name}: ERROR — {result['error']}")
        return False
    row_count = result.get("row_count", result.get("total", result.get("count", "?")))
    print(f"  ✓ {name}: {row_count} rows/items")
    return True


def run_tests():
    passed, failed = 0, 0

    tests = [
        # (name, result, expect_error)
        ("list_tables",          list_tables(),                                         False),
        ("get_schema",           get_schema("gold_bottleneck"),                         False),
        ("get_table_preview",    get_table_preview("gold_cap_normal", limit=3),         False),
        ("get_distinct_values",  get_distinct_values("gold_bottleneck", "site_code"),   False),

        ("get_capacity_summary",      get_capacity_summary(limit=10),       False),
        ("get_bottleneck_analysis",   get_bottleneck_analysis(limit=10),    False),
        ("get_demand_vs_supply",      get_demand_vs_supply(limit=10),       False),
        ("get_equipment_utilization", get_equipment_utilization(limit=10),  False),

        ("get_yield_prediction",     get_yield_prediction(limit=10),     False),
        ("get_yield_drivers",        get_yield_drivers(),                 False),
        ("get_ml_adjusted_capacity", get_ml_adjusted_capacity(limit=10), False),

        ("get_maintenance_alerts",  get_maintenance_alerts(limit=10),  False),
        ("get_failure_risk_trend",  get_failure_risk_trend(limit=10),  False),

        ("get_demand_forecast",   get_demand_forecast(limit=10),   False),
        ("get_forecast_accuracy", get_forecast_accuracy(limit=10), False),

        ("get_capex_recommendation", get_capex_recommendation(), False),
        ("get_capex_scenarios",      get_capex_scenarios(),       False),

        ("run_query (SELECT)",
         run_query("SELECT site_code, COUNT(*) as n FROM gold_bottleneck GROUP BY site_code LIMIT 5"),
         False),

        ("run_query (INSERT blocked)",
         run_query("INSERT INTO gold_bottleneck VALUES (1)"),
         True),   # expect_error=True — this SHOULD return an error
    ]

    print("=" * 60)
    print("MCP SERVER SMOKE TEST")
    print("=" * 60)

    for name, result, expect_error in tests:
        if check(name, result, expect_error):
            passed += 1
        else:
            failed += 1

    print()
    print("=" * 60)
    print(f"RESULT: {passed} passed / {failed} failed")
    print("=" * 60)

    if failed == 0:
        print("\n✅ MCP Server ready")
    else:
        print("\n❌ Fix errors above before proceeding")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
