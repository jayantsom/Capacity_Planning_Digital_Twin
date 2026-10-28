"""
Master runner: all raw data generators in dependency order.
"""

import time
from collections.abc import Callable
from copy import deepcopy
from importlib import import_module

from capacity_twin_core.logging import logger
from capacity_twin_core.runtime.database_paths import load_config
from data_operations.generator.generators.equipment_cost_reference import (
    generate_equipment_cost_reference,
)
from data_operations.generator.services.atomic_publication import (
    add_source_metadata,
    create_candidate,
    initialize_raw_databases,
    publish_candidate,
)
from data_operations.generator.services.control_publication import (
    publish_source_catalogs,
)
from data_operations.generator.validations.outputs import validate_outputs
from data_operations.generator.validations.preflight import validate_preflight


def _run_step(module_name: str, config: dict):
    """Load a numbered step without using invalid Python import syntax."""
    return import_module(f"data_operations.generator.steps.{module_name}").run(config)


def run_all(
    config: dict,
    *,
    progress_callback: Callable[[int, str, str], None] | None = None,
) -> dict:
    """Build and atomically publish all Raw databases."""
    report = progress_callback or (lambda _progress, _phase, _detail: None)
    start = time.time()
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║     CAPACITY PLANNING DIGITAL TWIN — DATA GENERATION    ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")

    report(3, "Preflight", "Validating dates, bounds, disk, and configuration")
    preflight_report = validate_preflight(config)
    run_id, candidate_dir = create_candidate(config)
    raw_dir = candidate_dir / "raw"
    initialize_raw_databases(raw_dir, config)
    candidate_config = deepcopy(config)
    candidate_config["paths"]["raw_sqlite"] = str(raw_dir)
    report(7, "Source catalogs", "Building canonical Reference and Mapping")
    catalog_report = publish_source_catalogs(
        candidate_config,
        candidate_dir,
        run_id,
    )
    candidate_config["control_publication"] = catalog_report
    logger.info(f"Preflight passed; building candidate {run_id}")

    logger.info("\n── PASS 1: Reference Data ──────────────────────────────────")
    report(12, "1 Reference data", "Generating sites, tests, and equipment")
    site_df, test_type_df, equip_df = _run_step("1_reference_data", candidate_config)

    logger.info("\n── PASS 2: Master Data ─────────────────────────────────────")
    report(24, "2 Products and routes", "Generating products, BOMs, and routes")
    product_df = _run_step("2_products_and_routes", candidate_config)

    logger.info("\n── PASS 3: Planning Data ───────────────────────────────────")
    report(38, "3 Planning targets", "Generating demand, yield, and test-time targets")
    demand_df, ttt_df, yield_df = _run_step("3_planning_targets", candidate_config)
    report(50, "4 Equipment and calendar", "Generating inventory and site calendars")
    equip_inv_df, site_soft_df = _run_step("4_equipment_and_calendar", candidate_config)

    logger.info("\n── PASS 4: Execution Data ──────────────────────────────────")
    report(68, "5 Execution", "Generating noisy manufacturing execution data")
    _run_step("5_execution", candidate_config)
    report(82, "6 Parameters", "Generating test parameters")
    _run_step("6_parameters", candidate_config)
    report(91, "7 Logs", "Generating operational logs")
    _run_step("7_logs", candidate_config)

    report(94, "8 Equipment costs", "Generating equipment cost references")
    equipment_cost_df = generate_equipment_cost_reference(candidate_config)

    report(96, "Validation", "Validating candidate databases before publication")
    add_source_metadata(
        raw_dir,
        candidate_config,
        source_run_id=run_id,
        extracted_at_utc=catalog_report["published_at"],
    )
    validation_report = validate_outputs(raw_dir, candidate_config)
    manifest_path = publish_candidate(
        run_id,
        candidate_dir,
        candidate_config,
        validation_report,
        preflight_report,
        catalog_report,
    )

    elapsed = time.time() - start
    logger.info("\n╔══════════════════════════════════════════════════════════╗")
    logger.info("║                  GENERATION SUMMARY                     ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")
    logger.info(
        f"  Reference:     {len(site_df)} sites | "
        f"{len(test_type_df)} test types | "
        f"{len(equip_df)} equipment"
    )
    logger.info(f"  Products:      {len(product_df)} records")
    logger.info(f"  Demand:        {len(demand_df):,} rows")
    logger.info(f"  Test time:     {len(ttt_df):,} rows")
    logger.info(f"  Yield:         {len(yield_df):,} rows")
    logger.info(f"  Equipment inv: {len(equip_inv_df):,} rows")
    logger.info(f"  Site soft:     {len(site_soft_df):,} rows")
    logger.info("  Machine execution:  [see per-month logs above]")
    logger.info("  Machine test param: [see per-month logs above]")
    logger.info("  Machine logs:       [see per-month logs above]")
    logger.info(f"\n  Total wall time: {elapsed:.1f}s")
    logger.info(f"  Manifest: {manifest_path}")
    logger.success("ALL GENERATORS COMPLETE.")
    return {
        "run_id": run_id,
        "manifest": str(manifest_path),
        "elapsed_seconds": round(elapsed, 2),
        "sites": len(site_df),
        "test_types": len(test_type_df),
        "products": len(product_df),
        "demand_rows": len(demand_df),
        "equipment_cost_rows": len(equipment_cost_df),
    }


def main() -> None:
    """Run every Raw generator with the Data Generator configuration."""
    run_all(load_config())


if __name__ == "__main__":
    main()
