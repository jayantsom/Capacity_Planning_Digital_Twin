"""Publish the retained effective-dated equipment-cost reference."""

from __future__ import annotations


def build_equipment_cost_reference(connection) -> int:
    """Create the Gold equipment-cost reference from its conformed source."""
    connection.execute("DROP TABLE IF EXISTS gold_equipment_cost_reference")
    connection.execute(
        """
        CREATE TABLE gold_equipment_cost_reference AS
        SELECT
            equipment_cost_reference_id,
            equipment_id,
            canonical_equipment_id,
            effective_start_date,
            effective_end_date,
            purchase_cost_usd,
            annual_maintenance_cost_usd,
            installation_cost_usd,
            lead_time_days,
            currency_code,
            cost_status
        FROM slvr_equipment_cost_reference
        WHERE is_valid
        """
    )
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM gold_equipment_cost_reference"
        ).fetchone()[0]
    )
