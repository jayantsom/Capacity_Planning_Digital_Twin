"""
Step 12: ML Models Pipeline
Run all ML models in sequence: demand forecast → yield prediction →
predictive maintenance → OEE anomaly detection → CapEx Monte Carlo.
"""

import logging
import time
from pathlib import Path

from src.utils.logger import logger as log
from src.ml.models.demand_forecast import run_demand_forecast
from src.ml.models.yield_prediction import run_yield_prediction
from src.ml.models.predictive_maintenance import run_predictive_maintenance
from src.ml.models.oee_anomaly import run_oee_anomaly
from src.ml.models.capex_montecarlo import run_capex_montecarlo

def run_ml_pipeline(priorities: list[int] | None = None) -> dict:
    """
    Run ML pipeline.

    Args:
        priorities: List of priority numbers to run (1-5). None = all.

    Returns:
        Dict with results per priority.
    """
    all_priorities = {
        1: ("Demand Forecasting (Prophet+XGBoost+LightGBM ensemble)", run_demand_forecast),
        2: ("Yield Prediction (XGBoost + SHAP)", run_yield_prediction),
        3: ("Predictive Maintenance (XGBoost classifier)", run_predictive_maintenance),
        4: ("OEE Anomaly Detection (Isolation Forest)", run_oee_anomaly),
        5: ("CapEx Monte Carlo Optimization (10K iterations)", run_capex_montecarlo),
    }

    to_run = {k: v for k, v in all_priorities.items() if priorities is None or k in priorities}
    results = {}

    total_start = time.time()

    for priority, (name, fn) in to_run.items():
        log.info("")
        log.info(f"[Priority {priority}] {name}")
        log.info("-" * 50)
        t0 = time.time()
        try:
            result = fn()
            elapsed = time.time() - t0
            results[priority] = {"status": "OK", "elapsed_s": round(elapsed, 1), **result}
            log.info(f"  ✓ Completed in {elapsed:.1f}s — {result.get('summary', '')}")
        except Exception as e:
            elapsed = time.time() - t0
            results[priority] = {"status": "ERROR", "elapsed_s": round(elapsed, 1), "error": str(e)}
            log.error(f"  ✗ FAILED after {elapsed:.1f}s: {e}", exc_info=True)

    total_elapsed = time.time() - total_start
    ok = sum(1 for r in results.values() if r["status"] == "OK")
    log.info("")
    log.info("=" * 70)
    log.info(f"ML PIPELINE COMPLETE — {ok}/{len(to_run)} succeeded in {total_elapsed:.1f}s")
    log.info("=" * 70)

    return results


if __name__ == "__main__":
    run_ml_pipeline()
