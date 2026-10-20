"""Small, deterministic formulas shared by pipeline and application code."""

from __future__ import annotations

from enum import StrEnum
from math import floor


class ResourceBehavior(StrEnum):
    """Supported relationships between demand and manufacturing resources."""

    ALTERNATIVE_POOL = "ALTERNATIVE_POOL"
    SERIAL_STEP = "SERIAL_STEP"
    PAIRED_FIXTURE = "PAIRED_FIXTURE"
    MULTI_DUT = "MULTI_DUT"
    STANDALONE = "STANDALONE"
    SHARED_POOL = "SHARED_POOL"
    DEDICATED = "DEDICATED"


def classify_bottleneck(gap_ratio: float | None) -> str:
    """Classify a capacity gap expressed as a ratio, not percentage points."""
    if gap_ratio is None:
        return "UNKNOWN"
    if gap_ratio < -0.15:
        return "CRITICAL"
    if gap_ratio < -0.08:
        return "HIGH"
    if gap_ratio < -0.03:
        return "MEDIUM"
    if gap_ratio < 0:
        return "LOW"
    if gap_ratio <= 0.05:
        return "BALANCED"
    return "EXCESS"


def calculate_oee(
    availability_ratio: float,
    performance_ratio: float,
    quality_ratio: float,
) -> float:
    """Calculate OEE after constraining each component to the valid range."""
    availability = min(1.0, max(0.0, availability_ratio))
    performance = min(1.0, max(0.0, performance_ratio))
    quality = min(1.0, max(0.0, quality_ratio))
    return availability * performance * quality


def calculate_effective_parallel_duts(
    tester_channels: int,
    licensed_ports: int,
    fixture_cavities: int,
    handler_sockets: int,
    parallel_efficiency: float,
) -> float:
    """Return usable parallel DUT capacity after physical and efficiency limits."""
    physical_limit = min(
        max(0, floor(tester_channels)),
        max(0, floor(licensed_ports)),
        max(0, floor(fixture_cavities)),
        max(0, floor(handler_sockets)),
    )
    efficiency = min(1.0, max(0.0, parallel_efficiency))
    return physical_limit * efficiency


def calculate_scenario_gap(
    behavior: ResourceBehavior,
    demands: list[float],
    resource_capacities: list[float],
    *,
    multi_dut_factor: float = 1.0,
) -> tuple[float, float, float]:
    """Return demand, usable capacity, and gap for one resource scenario."""
    clean_demands = [max(0.0, float(value)) for value in demands]
    clean_capacities = [max(0.0, float(value)) for value in resource_capacities]
    if not clean_demands or not clean_capacities:
        raise ValueError("A resource scenario requires demand and capacity values.")

    if behavior is ResourceBehavior.SHARED_POOL:
        demand = sum(clean_demands)
        capacity = sum(clean_capacities)
    elif behavior in {ResourceBehavior.SERIAL_STEP, ResourceBehavior.PAIRED_FIXTURE}:
        demand = clean_demands[0]
        capacity = min(clean_capacities)
    elif behavior is ResourceBehavior.MULTI_DUT:
        demand = clean_demands[0]
        capacity = sum(clean_capacities) * max(0.0, multi_dut_factor)
    else:
        demand = clean_demands[0]
        capacity = sum(clean_capacities)

    return demand, capacity, capacity - demand
