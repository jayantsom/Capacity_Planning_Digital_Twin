"""Conform the retained equipment-cost source contract."""

from __future__ import annotations

import duckdb


def build_equipment_cost_reference(
    connection: duckdb.DuckDBPyConnection,
    created_at: str,
) -> int:
    """Resolve equipment IDs for the effective-dated cost reference."""
    connection.execute("DROP TABLE IF EXISTS slvr_equipment_cost_reference")
    connection.execute(
        """
        CREATE TABLE slvr_equipment_cost_reference AS
        SELECT
            source.*,
            machine.equipment_id AS canonical_equipment_id,
            ? AS silver_created_at
        FROM brnz_equipment_cost_reference source
        LEFT JOIN reference.canonical.machine machine
          ON source.equipment_id = machine.equipment_id
        """,
        [created_at],
    )
    missing = int(
        connection.execute(
            """
            SELECT COUNT(*)
            FROM slvr_equipment_cost_reference
            WHERE canonical_equipment_id IS NULL
            """
        ).fetchone()[0]
    )
    if missing:
        raise ValueError(
            "slvr_equipment_cost_reference has "
            f"{missing} rows with unresolved canonical keys"
        )
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM slvr_equipment_cost_reference"
        ).fetchone()[0]
    )
