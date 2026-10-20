"""Shared local job state used by compute-heavy applications."""

from capacity_twin_core.jobs.manager import GLOBAL_JOBS, JobConflict, JobRegistry

__all__ = ["GLOBAL_JOBS", "JobConflict", "JobRegistry"]
