"""
ML Models Pipeline
Run all ML models in sequence: demand forecast → yield prediction →
predictive maintenance → OEE anomaly detection → CapEx Monte Carlo.
"""

import time
from collections.abc import Callable
from importlib import import_module

import duckdb

from capacity_twin_core.logging import logger as log
from decision_intelligence.publication import (
    create_candidate,
    discard_candidate,
    publish_candidate,
)

WORKFLOWS = {
    1: (
        "Demand Forecasting",
        "decision_intelligence.steps.1_demand_forecast",
    ),
    2: ("Yield Prediction", "decision_intelligence.steps.2_yield_prediction"),
    3: (
        "OEE Degradation Risk",
        "decision_intelligence.steps.3_oee_degradation_risk",
    ),
    4: (
        "OEE Anomaly Detection",
        "decision_intelligence.steps.4_oee_anomaly",
    ),
    5: (
        "CapEx Simulation",
        "decision_intelligence.steps.5_capex_simulation",
    ),
}

REQUIRED_OUTPUT_TABLES = {
    "gold_demand_forecast",
    "gold_forecast_accuracy_ml",
    "gold_yield_predictions",
    "gold_yield_shap",
    "gold_cap_ml_adjusted",
    "gold_maintenance_risk",
    "gold_maintenance_alerts",
    "gold_oee_anomalies",
    "gold_oee_anomaly_summary",
    "gold_capex_mc_summary",
    "gold_capex_mc_scenarios",
    # Keep display labels beside the ML outputs so dashboards stay self-contained.
    "slvr_ref_site",
    "slvr_ref_test_type",
    "slvr_ref_equipment",
    "slvr_prod_master",
}


def _validate_complete_outputs(database) -> None:
    """Require a complete Decision Intelligence publication."""
    with duckdb.connect(str(database), read_only=True) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables"
            ).fetchall()
        }
    missing = sorted(REQUIRED_OUTPUT_TABLES - tables)
    if missing:
        raise ValueError(f"ML candidate is incomplete; missing tables: {missing}")


def run_ml_pipeline(
    priorities: list[int] | None = None,
    *,
    progress_callback: Callable[[int, str, str], None] | None = None,
) -> dict:
    """
    Run ML pipeline.

    Args:
        priorities: List of priority numbers to run (1-5). None = all.

    Returns:
        Dict with results per priority.
    """
    report = progress_callback or (lambda _progress, _phase, _detail: None)
    selected = sorted(set(priorities or WORKFLOWS))
    invalid = sorted(set(selected) - set(WORKFLOWS))
    if invalid or not selected:
        raise ValueError(f"Invalid workflow priorities: {invalid or selected}")
    to_run = {
        priority: (name, import_module(module_name).run)
        for priority, (name, module_name) in WORKFLOWS.items()
        if priority in selected
    }
    results = {}
    candidate = create_candidate(preserve_existing=len(selected) < len(WORKFLOWS))

    total_start = time.time()

    for index, (priority, (name, fn)) in enumerate(to_run.items()):
        report(
            5 + int(index / len(to_run) * 85),
            name,
            f"Running workflow {priority} of {len(WORKFLOWS)}",
        )
        log.info("")
        log.info(f"[Priority {priority}] {name}")
        log.info("-" * 50)
        t0 = time.time()
        try:
            result = fn()
            elapsed = time.time() - t0
            results[priority] = {"status": "OK", "elapsed_s": round(elapsed, 1), **result}
            log.info(f"  ✓ Completed in {elapsed:.1f}s — {result.get('summary', '')}")
        except ValueError as e:
            elapsed = time.time() - t0
            results[priority] = {
                "status": "NOT_EVALUABLE",
                "elapsed_s": round(elapsed, 1),
                "reason": str(e),
            }
            log.warning(f"  Not evaluable after {elapsed:.1f}s: {e}")
        except Exception as e:  # noqa: BLE001 - isolate workflows and preserve prior publication
            elapsed = time.time() - t0
            results[priority] = {"status": "ERROR", "elapsed_s": round(elapsed, 1), "error": str(e)}
            log.error(f"  ✗ FAILED after {elapsed:.1f}s: {e}", exc_info=True)

    total_elapsed = time.time() - total_start
    ok = sum(1 for r in results.values() if r["status"] == "OK")
    if ok == len(to_run):
        try:
            report(95, "Validation", "Checking complete ML outputs before publication")
            _validate_complete_outputs(candidate.database)
            merged_results = {**candidate.previous_results, **results}
            published = publish_candidate(candidate, merged_results)
            log.info(f"Published validated ML database: {published}")
        except Exception:
            discard_candidate(candidate)
            raise
    else:
        discard_candidate(candidate)
        log.error("ML candidate was not published; the previous artifacts remain active")
    log.info("")
    log.info("=" * 70)
    log.info(f"ML PIPELINE COMPLETE — {ok}/{len(to_run)} succeeded in {total_elapsed:.1f}s")
    log.info("=" * 70)

    return results


def main() -> None:
    """Run all five existing ML workflows."""
    run_ml_pipeline()


if __name__ == "__main__":
    main()
