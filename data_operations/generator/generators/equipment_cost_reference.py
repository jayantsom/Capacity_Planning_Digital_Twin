"""Generate source equipment cost reference data."""

from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd

from capacity_twin_core.runtime.database_paths import get_sqlite_path
from data_operations.generator.generators.reference_data import (
    FIXTURES,
    SYSTEMS,
    write_to_sqlite,
)


def _cost_reference_id(equipment_id: str) -> str:
    payload = f"equipment-cost|{equipment_id}".encode()
    return hashlib.sha256(payload).hexdigest()[:24]


def generate_equipment_cost_reference(config: dict[str, Any]) -> pd.DataFrame:
    """Write one effective-dated cost record for each equipment definition."""
    start = config["data_generation"]["start_date_actual"]
    end = config["data_generation"]["end_date_forecast"]
    rows = [
        {
            "equipment_cost_reference_id": _cost_reference_id(equipment[0]),
            "equipment_id": equipment[0],
            "effective_start_date": start,
            "effective_end_date": end,
            "purchase_cost_usd": 65_000 + index * 12_500,
            "annual_maintenance_cost_usd": 4_500 + index * 700,
            "installation_cost_usd": 7_500 + index * 900,
            "lead_time_days": 45 + (index % 8) * 15,
            "currency_code": "USD",
            "cost_status": "APPROVED",
        }
        for index, equipment in enumerate([*SYSTEMS, *FIXTURES])
    ]
    frame = pd.DataFrame(rows)
    write_to_sqlite(
        frame,
        "equipment_cost_reference",
        get_sqlite_path(config["databases"]["raw"]["machine"], config),
    )
    return frame
