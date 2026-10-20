"""One qualification and ramp calendar shared by every generator."""

from __future__ import annotations

from datetime import date

NPI_START_DATES = {
    "RAN-AAU-35128-004": date(2024, 7, 1),
    "RAN-MWR-3900-009": date(2025, 1, 1),
    "BBP-BBU-6GPR-013": date(2025, 4, 1),
    "BBP-DPU-G4-015": date(2025, 7, 1),
    "MWT-DBU-150G-021": date(2025, 10, 1),
    "RFC-TFL-S6G-026": date(2026, 1, 1),
    "RFC-DUP-WB-030": date(2025, 4, 1),
    "PWR-PAB-28G-034": date(2025, 7, 1),
    "WLS-CPE-5GF-045": date(2026, 2, 1),
    "BBP-CUA-EDGE-046": date(2026, 3, 1),
    "BBP-DUA-EDGE-047": date(2026, 5, 1),
    "OPT-MOD-RXTX-048": date(2026, 7, 1),
}


def npi_ramp(product_number: str, on_date: date) -> float:
    """Return zero before qualification and a 12-month linear ramp after it."""
    start = NPI_START_DATES.get(product_number)
    if start is None:
        return 1.0
    if on_date < start:
        return 0.0
    elapsed = (on_date.year - start.year) * 12 + on_date.month - start.month
    return min(1.0, (elapsed + 1) / 12)
