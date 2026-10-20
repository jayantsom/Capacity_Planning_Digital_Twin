"""Fast Bronze tests for stable pagination and explicit duplicate handling."""

import sqlite3
from pathlib import Path

import duckdb

from data_operations.pipeline.pipeline.bronze.ingest import (
    _mark_duplicates,
    iter_sqlite_chunks,
)


def test_keyset_pagination_is_ordered_and_survives_rowid_gaps(tmp_path: Path) -> None:
    """Read each immutable source row once without LIMIT/OFFSET instability."""
    database = tmp_path / "source.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE facts(value VARCHAR)")
        connection.executemany(
            "INSERT INTO facts VALUES (?)", [("a",), ("b",), ("c",), ("d",)]
        )
        connection.execute("DELETE FROM facts WHERE value = 'b'")
        chunks = list(iter_sqlite_chunks(connection, "facts", chunk_size=2))

    assert [row for chunk in chunks for row in chunk["value"]] == ["a", "c", "d"]
    assert [row for chunk in chunks for row in chunk["_source_rowid"]] == [1, 3, 4]


def test_duplicate_natural_keys_are_flagged_not_summed(tmp_path: Path) -> None:
    """Retain duplicate Raw rows while rejecting every repeat after the first."""
    database = tmp_path / "bronze.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            CREATE TABLE brnz_fact (
                _source_rowid INTEGER,
                business_key VARCHAR,
                quantity INTEGER,
                is_valid BOOLEAN,
                invalid_reason VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO brnz_fact VALUES
                (1, 'A', 10, true, NULL),
                (2, 'A', 10, true, NULL),
                (3, 'B', 7, false, 'SOURCE_ERROR')
            """
        )
        _mark_duplicates(connection, "brnz_fact", ["business_key"])
        rows = connection.execute(
            """
            SELECT business_key, quantity, is_valid, is_duplicate, duplicate_rank,
                   invalid_reason
            FROM brnz_fact
            ORDER BY _source_rowid
            """
        ).fetchall()

    assert rows[0][2:] == (True, False, 1, None)
    assert rows[1][2:] == (False, True, 2, "DUPLICATE_NATURAL_KEY")
    assert rows[2][2:] == (False, False, 1, "SOURCE_ERROR")


def test_duplicate_marker_handles_an_all_null_reason_column(tmp_path: Path) -> None:
    """Cast an inferred NULL column before adding a text rejection reason."""
    database = tmp_path / "bronze-null-reason.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            CREATE TABLE brnz_fact AS
            SELECT *
            FROM (
                VALUES
                    (1, 'A', true, NULL),
                    (2, 'A', true, NULL)
            ) AS source(_source_rowid, business_key, is_valid, invalid_reason)
            """
        )
        _mark_duplicates(connection, "brnz_fact", ["business_key"])
        reasons = connection.execute(
            "SELECT invalid_reason FROM brnz_fact ORDER BY _source_rowid"
        ).fetchall()

    assert reasons == [(None,), ("DUPLICATE_NATURAL_KEY",)]
