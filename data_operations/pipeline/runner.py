"""Ordered, retryable, atomic Bronze-to-Serving pipeline entry point."""

from __future__ import annotations

import argparse
import importlib
import json
from collections.abc import Callable
from pathlib import Path

from capacity_twin_core.runtime.database_paths import get_runtime_home, load_config
from data_operations.pipeline.pipeline.run_state import PipelineRun, rollback

STAGES = (
    ("bronze", "data_operations.pipeline.steps.1_bronze"),
    ("silver", "data_operations.pipeline.steps.2_silver"),
    ("gold", "data_operations.pipeline.steps.3_gold"),
    ("serving", "data_operations.pipeline.steps.4_serving"),
)


def run_pipeline(
    config: dict,
    *,
    retry_of: str | None = None,
    progress_callback: Callable[[int, str, str], None] | None = None,
) -> PipelineRun:
    """Build all candidates in order and promote only the complete run."""
    report = progress_callback or (lambda _progress, _phase, _detail: None)
    candidate = PipelineRun(config, retry_of=retry_of)
    stage_name = "initialization"
    try:
        for index, (stage_name, module_name) in enumerate(STAGES):
            report(
                5 + index * 22,
                stage_name.title(),
                f"Building the {stage_name.title()} layer",
            )
            started = candidate.begin_stage(stage_name)
            module = importlib.import_module(module_name)
            counts = module.run(config, candidate)
            candidate.complete_stage(stage_name, started, counts=counts)
        report(96, "Promotion", "Validating and promoting the complete run")
        candidate.promote()
    except Exception as error:
        candidate.fail(stage_name, error)
        raise
    return candidate


def retry_run(config: dict, failed_run_id: str) -> PipelineRun:
    """Start a clean candidate linked to a prior failed run."""
    manifest_path = (
        Path(config["paths"]["runtime_home"])
        / "artifacts"
        / failed_run_id
        / "manifest.json"
    )
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Retry source manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "FAILED":
        raise ValueError("Only failed candidates can be retried")
    return run_pipeline(config, retry_of=failed_run_id)


def main() -> None:
    """Run, retry, or roll back the local pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("run", help="Build and promote a new candidate")
    retry_parser = subcommands.add_parser("retry", help="Retry a failed candidate")
    retry_parser.add_argument("run_id")
    subcommands.add_parser("rollback", help="Activate the previous known-good run")
    args = parser.parse_args()

    if args.command == "rollback":
        print(rollback(get_runtime_home()))
        return

    config = load_config()
    candidate = (
        retry_run(config, args.run_id)
        if args.command == "retry"
        else run_pipeline(config)
    )
    print(candidate.paths.run_id)


if __name__ == "__main__":
    main()
