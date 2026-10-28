"""
Month key utilities.
month_key format: YYYYMM integer (e.g. 202301 = January 2023)
All planning tables use this as the time dimension key.
"""

from datetime import date

from dateutil.relativedelta import relativedelta


def date_to_month_key(d: date) -> int:
    """Convert date to YYYYMM integer."""
    return d.year * 100 + d.month


def month_key_to_date(mk: int) -> date:
    """Convert YYYYMM integer to first day of that month."""
    year = mk // 100
    month = mk % 100
    return date(year, month, 1)


def month_label_to_key(label: str) -> int:
    """
    Convert month label string to integer key.
    jan_2023 → 202301
    feb_2026 → 202602
    """
    month_map = {
        "jan": 1,  "feb": 2,  "mar": 3,  "apr": 4,
        "may": 5,  "jun": 6,  "jul": 7,  "aug": 8,
        "sep": 9,  "oct": 10, "nov": 11, "dec": 12,
    }
    parts = label.split("_")
    month_num = month_map.get(parts[0], 1)
    year = int(parts[1])
    return year * 100 + month_num


def month_key_range(start_mk: int, end_mk: int) -> list[int]:
    """Generate list of month keys from start to end inclusive."""
    keys = []
    current = month_key_to_date(start_mk)
    end = month_key_to_date(end_mk)
    while current <= end:
        keys.append(date_to_month_key(current))
        current += relativedelta(months=1)
    return keys


def month_key_label(mk: int) -> str:
    """Convert month key to column label e.g. 202301 → jan_2023."""
    d = month_key_to_date(mk)
    return d.strftime("%b_%Y").lower()


def get_actual_month_keys(start: date, end: date) -> list[int]:
    """Return configured actual month keys."""
    return month_key_range(date_to_month_key(start), date_to_month_key(end))


def get_forecast_month_keys(start: date, end: date) -> list[int]:
    """Return configured forecast month keys."""
    return month_key_range(date_to_month_key(start), date_to_month_key(end))


def get_all_month_keys(start: date, end: date) -> list[int]:
    """Return month keys for an explicit configured date interval."""
    return month_key_range(date_to_month_key(start), date_to_month_key(end))


def is_actual(mk: int, cutoff: date) -> bool:
    """Return whether a month falls on or before the configured cutoff."""
    return mk <= date_to_month_key(cutoff)


def working_days_in_month(mk: int, days_normal: int) -> int:
    """Return working days with slight monthly variation around normal."""
    import hashlib

    # A digest avoids process-dependent random state in shared date logic.
    offset = int.from_bytes(hashlib.sha256(str(mk).encode()).digest()[:2], "big") % 3 - 1
    return max(18, min(days_normal + offset, 27))