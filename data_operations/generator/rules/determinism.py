"""Stable identities and random seeds for synthetic records."""

from __future__ import annotations

import hashlib


def stable_seed(root_seed: int, *business_key: object) -> int:
    """Return a process-independent NumPy-compatible seed.

    Python's built-in hash is salted for each process, so it must never be
    used for generated business data.
    """
    payload = "|".join([str(root_seed), *(str(value) for value in business_key)])
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def stable_id(namespace: str, *business_key: object) -> str:
    """Return a readable namespace plus a stable SHA-256 identity."""
    payload = "|".join([namespace, *(str(value) for value in business_key)])
    return f"{namespace}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"
