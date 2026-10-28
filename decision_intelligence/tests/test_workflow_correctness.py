"""Fast synthetic regression tests for the five existing ML workflows."""

from __future__ import annotations

import json

import duckdb
import numpy as np
import pandas as pd
import pytest

from decision_intelligence import ml_support, publication
from decision_intelligence.ml.models.capex_montecarlo import (
    SimInputs,
    _stream_seed,
    simulate_equipment_needed,
)
from decision_intelligence.ml.models.demand_forecast import (
    build_features,
    is_intermittent_demand,
    prepare_demand_series,
    supports_yearly_seasonality,
)
from decision_intelligence.ml.models.oee_anomaly import (
    assign_severity,
    calibrate_severity_thresholds,
)
from decision_intelligence.ml.models.predictive_maintenance import (
    aggregate_equipment_grain,
    generate_failure_labels,
)
from decision_intelligence.ml.models.yield_prediction import _feat_cols as yield_feature_columns
from decision_intelligence.ml.models.yield_prediction import (
    build_yield_features,
    recalculate_capacity_with_ml_yield,
)


def test_demand_lags_do_not_cross_series_and_rolling_excludes_target() -> None:
    frame = pd.DataFrame(
        {
            "product_id": ["A", "A", "A", "B", "B", "B"],
            "site_id": ["S"] * 6,
            "month": [202401, 202402, 202403, 202401, 202402, 202403],
            "demand": [10.0, 20.0, 999.0, 100.0, 200.0, 300.0],
        }
    )
    featured = build_features(frame)
    a_march = featured.query("product_id == 'A' and month == 202403").iloc[0]
    b_january = featured.query("product_id == 'B' and month == 202401").iloc[0]

    assert a_march["demand_lag1"] == 20.0
    assert a_march["demand_roll3_mean"] == 15.0
    assert pd.isna(b_january["demand_lag1"])
    assert pd.isna(b_january["demand_roll3_mean"])


def test_demand_grain_deduplicates_tests_and_rejects_conflicts() -> None:
    frame = pd.DataFrame(
        {
            "product_id": ["P", "P"],
            "site_id": ["S", "S"],
            "test_type_id": ["ICT", "FCT"],
            "month": [202401, 202401],
            "demand": [50.0, 50.0],
            "is_actual": [1, 1],
        }
    )
    result = prepare_demand_series(frame)
    assert len(result) == 1
    assert result.iloc[0]["demand"] == 50.0

    frame.loc[1, "demand"] = 60.0
    with pytest.raises(ValueError, match="Conflicting demand"):
        prepare_demand_series(frame)


def test_croston_selection_depends_on_zero_demand_not_product_age() -> None:
    intermittent = pd.Series([0.0, 0.0, 10.0, 0.0, 0.0, 8.0, 0.0, 0.0])
    short_but_continuous = pd.Series([4.0, 6.0, 8.0, 9.0, 10.0, 11.0])

    assert is_intermittent_demand(intermittent)
    assert not is_intermittent_demand(short_but_continuous)


def test_prophet_requires_two_complete_years_for_yearly_seasonality() -> None:
    less_than_two_years = pd.Series(pd.period_range("2025-01", periods=24, freq="M"))
    complete_two_year_span = pd.Series(pd.period_range("2024-01", periods=25, freq="M"))

    def to_month_keys(values: pd.Series) -> pd.Series:
        return values.map(lambda value: value.year * 100 + value.month)

    assert not supports_yearly_seasonality(to_month_keys(less_than_two_years))
    assert supports_yearly_seasonality(to_month_keys(complete_two_year_span))


def test_temporal_split_uses_unique_month_boundaries() -> None:
    frame = pd.DataFrame(
        {
            "month": np.repeat(
                [202301, 202302, 202303, 202304, 202305, 202306, 202307, 202308],
                2,
            )
        }
    )
    train, validation, holdout = ml_support.temporal_split(
        frame,
        holdout_months=2,
        validation_months=2,
        minimum_train_months=4,
    )
    assert train["month"].max() < validation["month"].min()
    assert validation["month"].max() < holdout["month"].min()


def test_feature_store_removes_resource_fanout_before_ml() -> None:
    conn = duckdb.connect()
    rows = pd.DataFrame(
        {
            "site_code": ["S", "S"],
            "product_number": ["P", "P"],
            "test_type": ["ICT", "ICT"],
            "month_key": [202401, 202401],
            "planning_version_id": ["plan-2026-10-31", "plan-2026-10-31"],
            "demand_qty": [100.0, 100.0],
            "target_yield": [0.95, 0.95],
            "target_test_time_sec": [60.0, 60.0],
            "equip_qty_available": [2, 4],
            "utilization_rate": [0.8, 0.9],
            "demand_lag_1": [100.0, 999.0],
        }
    )
    conn.register("feature_rows", rows)
    conn.execute("CREATE TABLE gold_ml_feature_store AS SELECT * FROM feature_rows")

    result = ml_support.load_feature_store(conn)

    assert len(result) == 1
    assert "equip_qty_available" not in result
    assert "demand_lag_1" not in result
    assert result.iloc[0]["demand"] == 100.0


def test_yield_features_use_measured_label_and_keep_stable_ids() -> None:
    frame = pd.DataFrame(
        {
            "feature_row_id": ["row-2", "row-1"],
            "site_id": ["S", "S"],
            "product_id": ["P", "P"],
            "test_type_id": ["ICT", "ICT"],
            "planning_version_id": ["plan-2026-10-31", "plan-2026-10-31"],
            "month": [202402, 202401],
            "measured_yield": [0.70, 0.90],
            "target_yield": [0.99, 0.99],
            "avg_oee": [0.8, 0.9],
            "availability": [0.9, 0.95],
            "performance": [0.9, 0.95],
            "quality": [0.7, 0.9],
            "demand": [100.0, 90.0],
        }
    )
    result = build_yield_features(frame)
    february = result.query("month == 202402").iloc[0]
    assert february["measured_yield_lag1"] == 0.90
    assert february["measured_yield_roll3_mean"] == 0.90
    assert february["feature_row_id"] == "row-2"
    assert "target_yield_lag1" not in result
    safe_features = yield_feature_columns(result)
    assert "avg_oee" not in safe_features
    assert "quality" not in safe_features
    assert "avg_oee_lag1" in safe_features


def test_maintenance_is_unique_at_equipment_grain() -> None:
    frame = pd.DataFrame(
        {
            "equipment_id": ["E1", "E1"],
            "site_id": ["S", "S"],
            "test_type_id": ["ICT", "ICT"],
            "month": [202401, 202401],
            "product_id": ["P1", "P2"],
            "demand": [10.0, 20.0],
            "measured_yield": [0.9, 0.8],
            "avg_oee": [0.7, 0.7],
        }
    )
    result = aggregate_equipment_grain(frame)
    assert len(result) == 1
    assert result.iloc[0]["demand"] == 30.0
    assert result.iloc[0]["avg_oee"] == pytest.approx(0.7)


def test_maintenance_labels_censor_rows_without_full_future_horizon() -> None:
    frame = pd.DataFrame(
        {
            "equipment_id": ["E1"] * 5,
            "site_id": ["S"] * 5,
            "test_type_id": ["ICT"] * 5,
            "month": [202401, 202402, 202403, 202404, 202405],
            "avg_oee": [0.95, 0.94, 0.70, 0.93, 0.92],
        }
    )
    labeled = generate_failure_labels(frame)
    assert labeled.iloc[0]["degradation_label"] == 1
    assert labeled["degradation_label"].tail(3).isna().all()


def test_anomaly_severity_is_independent_of_scored_batch_rank() -> None:
    thresholds = calibrate_severity_thresholds(np.linspace(-1.0, 1.0, 100))
    one = assign_severity(pd.Series([-0.95]), thresholds).iloc[0]
    many = assign_severity(pd.Series([-0.95, 0.2, 0.8]), thresholds).iloc[0]
    assert one == many


def test_capex_samples_yield_and_uses_independent_deterministic_streams() -> None:
    low_yield = SimInputs(100_000, 0.1, 2, 8, 0.7, 0.8, 0.9, 100, 2, 20, 8, 0.1, 0.9)
    high_yield = low_yield._replace(yield_alpha=80, yield_beta=2)
    low = simulate_equipment_needed(low_yield, n=2000, seed=123)
    high = simulate_equipment_needed(high_yield, n=2000, seed=123)

    assert low.mean() > high.mean()
    assert np.array_equal(low, simulate_equipment_needed(low_yield, n=2000, seed=123))
    assert _stream_seed("S1", "ICT") != _stream_seed("S2", "ICT")


def test_model_artifact_checksum_blocks_modified_pickle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ml_support, "_ACTIVE_MODELS_DIR", tmp_path)
    path = ml_support.save_model(
        {"coefficient": 1},
        "tiny",
        {"feature_schema": ["x"], "training_run": "unit-test"},
    )
    metadata = json.loads((tmp_path / "tiny_meta.json").read_text(encoding="utf-8"))
    assert metadata["artifact_sha256"] == ml_support.file_sha256(path)
    path.write_bytes(path.read_bytes() + b"modified")
    with pytest.raises(ValueError, match="checksum mismatch"):
        ml_support.load_model("tiny")


def test_capacity_merge_keeps_planning_versions_and_gap_units() -> None:
    conn = duckdb.connect()
    gcm = pd.DataFrame(
        {
            "product_number": ["P", "P"],
            "site_code": ["S", "S"],
            "test_type": ["ICT", "ICT"],
            "month_key": [202401, 202401],
            "planning_version_id": ["plan-2025-10-31", "plan-2026-10-31"],
            "target_yield": [0.8, 0.8],
            "handling_time_sec": [10.0, 10.0],
            "target_test_time_sec": [90.0, 90.0],
            "utilization_rate": [0.8, 0.8],
            "hours_per_shift_normal": [8.0, 8.0],
            "allowance_pct": [0.1, 0.1],
            "productivity_pct": [0.9, 0.9],
            "working_days_normal": [20.0, 20.0],
            "shifts_per_day_normal": [2.0, 2.0],
            "equip_qty_available": [1.0, 1.0],
            "effective_demand_qty": [1_000.0, 1_000.0],
        }
    )
    conn.register("gcm", gcm)
    conn.execute("CREATE TABLE gold_gcm_base AS SELECT * FROM gcm")
    predictions = pd.DataFrame(
        {
            "product_id": ["P", "P"],
            "site_id": ["S", "S"],
            "test_type_id": ["ICT", "ICT"],
            "month": [202401, 202401],
            "planning_version_id": ["plan-2025-10-31", "plan-2026-10-31"],
            "predicted_yield": [0.7, 0.9],
        }
    )
    result = recalculate_capacity_with_ml_yield(conn, predictions)
    assert len(result) == 2
    assert set(result["yield_used"]) == {0.7, 0.9}
    assert np.allclose(
        result["capacity_gap_pct_ml"],
        result["capacity_gap_ratio_ml"] * 100,
    )


def test_publication_changes_atomic_pointer_only_after_validation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CAPACITY_TWIN_HOME", str(tmp_path))
    pipeline_run = "pipeline-test"
    pipeline_root = tmp_path / "artifacts" / pipeline_run
    pipeline_root.mkdir(parents=True)
    files = {}
    for layer in ("bronze", "silver", "gold", "serving"):
        path = pipeline_root / f"{layer}.duckdb"
        with duckdb.connect(str(path)) as conn:
            conn.execute(f"CREATE TABLE {layer}_input(value INTEGER)")
        files[path.name] = {"sha256": ml_support.file_sha256(path)}
    source_root = tmp_path / "source_bundles" / "source-test"
    source_root.mkdir(parents=True)
    source_files = {}
    for role in ("reference", "mapping"):
        path = source_root / f"{role}.duckdb"
        with duckdb.connect(str(path)):
            pass
        source_files[path.name] = {"role": role, "path": str(path)}
    source_manifest = source_root / "source_bundle_manifest.json"
    source_manifest.write_text(json.dumps({"files": source_files}), encoding="utf-8")
    pipeline_manifest = pipeline_root / "manifest.json"
    pipeline_manifest.write_text(
        json.dumps(
            {
                "source_bundle_run_id": "source-test",
                "source_bundle_checksum": "source-checksum",
                "source_bundle_manifest": str(source_manifest),
                "files": files,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "current.json").write_text(
        json.dumps(
            {"active_run_id": pipeline_run, "manifest": str(pipeline_manifest)}
        ),
        encoding="utf-8",
    )

    candidate = publication.create_candidate()
    candidate_conn = duckdb.connect(str(candidate.database))
    candidate_conn.execute("CREATE TABLE ml_test_output AS SELECT 1 AS value")
    candidate_conn.close()
    published = publication.publish_candidate(candidate, {1: {"status": "OK"}})

    pointer = json.loads((tmp_path / "ml_current.json").read_text(encoding="utf-8"))
    release = json.loads((tmp_path / "release_current.json").read_text(encoding="utf-8"))
    assert published.is_file()
    assert pointer["database_sha256"] == ml_support.file_sha256(published)
    assert ml_support.published_database_path() == published.resolve()
    assert release["ml"]["input_pipeline_run_id"] == pipeline_run
