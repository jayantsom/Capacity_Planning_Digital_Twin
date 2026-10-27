"""Tests for reopening the atomically promoted serving database."""

import json

from operations_assistant.agentic.mcp_server import db


def test_database_path_tracks_active_pointer(tmp_path, monkeypatch):
    first = tmp_path / "artifacts" / "run-one" / "serving.duckdb"
    second = tmp_path / "artifacts" / "run-two" / "serving.duckdb"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.touch()
    second.touch()
    monkeypatch.setattr(db, "get_runtime_home", lambda: tmp_path)
    monkeypatch.setattr(
        db,
        "load_app_config",
        lambda _name: {"databases": {"serving": "serving.duckdb"}},
    )

    pointer = tmp_path / "current.json"
    pointer.write_text(
        json.dumps({
            "active_run_id": "run-one",
            "serving_database": str(first),
        }),
        encoding="utf-8",
    )
    assert db.database_path() == first

    pointer.write_text(
        json.dumps({
            "active_run_id": "run-two",
            "serving_database": str(second),
        }),
        encoding="utf-8",
    )
    assert db.database_path() == second
