"""Offline Data Explorer API, refresh, and identifier tests."""

import json
import sqlite3

import duckdb
from fastapi.testclient import TestClient

from data_explorer.backend import main


def _write_run(root, run_id: str, value: str) -> None:
    artifact = root / "artifacts" / run_id
    raw_dir = artifact / "raw" / "sqlite"
    raw_dir.mkdir(parents=True)
    sqlite_path = raw_dir / "items.db"
    with sqlite3.connect(sqlite_path) as conn:
        conn.execute("CREATE TABLE raw_items(id INTEGER, label TEXT)")
        conn.execute("INSERT INTO raw_items VALUES (1, ?)", [value])

    serving_path = artifact / main.PIPELINE_CONFIG["databases"]["serving"]
    conn = duckdb.connect(str(serving_path))
    conn.execute("CREATE TABLE gold_values(id INTEGER, label VARCHAR)")
    conn.execute("INSERT INTO gold_values VALUES (1, ?)", [value])
    conn.close()


def _promote(root, run_id: str) -> None:
    (root / "current.json").write_text(
        json.dumps({
            "active_run_id": run_id,
            "serving_database": str(
                root / "artifacts" / run_id / "serving.duckdb"
            ),
        }),
        encoding="utf-8",
    )


def test_sources_and_data_refresh_after_promotion(tmp_path, monkeypatch):
    _write_run(tmp_path, "run-one", "first")
    _write_run(tmp_path, "run-two", "second")
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    _promote(tmp_path, "run-one")
    client = TestClient(main.app)

    first = client.get(
        "/explorer/api/data/raw_items/raw_items?page=1&page_size=10"
    )
    assert first.status_code == 200
    assert first.json()["rows"][0]["label"] == "first"

    _promote(tmp_path, "run-two")
    second = client.get(
        "/explorer/api/data/raw_items/raw_items?page=1&page_size=10"
    )
    assert second.status_code == 200
    assert second.json()["rows"][0]["label"] == "second"


def test_query_guard_and_identifier_allowlists(tmp_path, monkeypatch):
    _write_run(tmp_path, "run-one", "safe")
    _promote(tmp_path, "run-one")
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    client = TestClient(main.app)

    valid = client.post(
        "/explorer/api/query/duckdb_serving",
        json={"sql": "SELECT id, label FROM gold_values", "limit": 1},
    )
    assert valid.status_code == 200
    assert valid.json()["row_count"] == 1

    malicious = [
        "SELECT * FROM gold_values; DROP TABLE gold_values",
        "SELECT * FROM read_csv_auto('secret.csv')",
        "DELETE FROM gold_values",
        "SELECT secret FROM gold_values",
    ]
    for sql in malicious:
        response = client.post(
            "/explorer/api/query/duckdb_serving",
            json={"sql": sql, "limit": 10},
        )
        assert response.status_code == 400

    bad_identifier = client.get(
        "/explorer/api/data/duckdb_serving/gold_values"
        "?filters=%7B%22id%5C%22%20OR%201%3D1--%22%3A1%7D"
    )
    assert bad_identifier.status_code == 400


def test_catalog_assigns_each_object_one_unique_identity(tmp_path, monkeypatch):
    _write_run(tmp_path, "run-one", "safe")
    _promote(tmp_path, "run-one")
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    sources = TestClient(main.app).get("/explorer/api/sources").json()

    objects = [
        table
        for source in sources
        for table in source.get("tables", [])
    ]
    identities = [table["canonical_object_id"] for table in objects]
    assert identities
    assert len(identities) == len(set(identities))
    assert all(table["owner_layer"] == table["layer"].upper() for table in objects)


def test_explorer_cors_is_localhost_only():
    client = TestClient(main.app)
    local = client.options(
        "/explorer/api/sources",
        headers={
            "Origin": "http://127.0.0.1:8000",
            "Access-Control-Request-Method": "GET",
        },
    )
    remote = client.options(
        "/explorer/api/sources",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert local.headers["access-control-allow-origin"] == "http://127.0.0.1:8000"
    assert "access-control-allow-origin" not in remote.headers
