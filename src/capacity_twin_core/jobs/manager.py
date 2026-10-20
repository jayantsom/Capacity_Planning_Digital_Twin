"""Thread-safe local jobs with status files outside the repository."""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capacity_twin_core.runtime.database_paths import get_runtime_home

JobUpdate = Callable[[int, str, str], None]
JobRunner = Callable[[JobUpdate], dict[str, Any] | None]


class JobConflict(RuntimeError):
    """Raised when another heavy local job is already running."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Write a complete status file in one replace operation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


class JobRegistry:
    """Run one heavy job at a time and expose safe progress."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._threads: dict[str, threading.Thread] = {}

    @property
    def directory(self) -> Path:
        return get_runtime_home() / "jobs"

    def start(
        self,
        kind: str,
        runner: JobRunner,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Start one background job after checking the global lock."""
        with self._lock:
            self._recover_interrupted()
            active = self.active()
            if active:
                raise JobConflict(
                    f"{active['kind']} job {active['job_id']} is already running"
                )
            job_id = f"{kind}-{uuid.uuid4().hex[:10]}"
            job = {
                "job_id": job_id,
                "kind": kind,
                "status": "PENDING",
                "progress_pct": 0,
                "phase": "Queued",
                "detail": "Waiting to start",
                "created_at": _utc_now(),
                "started_at": None,
                "completed_at": None,
                "metadata": metadata or {},
                "result": None,
                "error": None,
            }
            self._jobs[job_id] = job
            self._write(job)
            thread = threading.Thread(
                target=self._execute,
                args=(job_id, runner),
                name=job_id,
                daemon=True,
            )
            self._threads[job_id] = thread
            thread.start()
            return dict(job)

    def active(self) -> dict[str, Any] | None:
        """Return the running in-process job, if one exists."""
        for job_id, thread in list(self._threads.items()):
            if thread.is_alive():
                return dict(self._jobs[job_id])
        return None

    def get(self, job_id: str) -> dict[str, Any]:
        """Read one job from memory or its persisted status file."""
        self._recover_interrupted()
        with self._lock:
            if job_id in self._jobs:
                return dict(self._jobs[job_id])
        path = self.directory / f"{job_id}.json"
        if not path.is_file():
            raise KeyError(job_id)
        job = json.loads(path.read_text(encoding="utf-8"))
        if job.get("status") in {"PENDING", "RUNNING"}:
            job.update(
                {
                    "status": "INTERRUPTED",
                    "completed_at": _utc_now(),
                    "detail": "The application stopped before this job completed",
                }
            )
            _atomic_json(path, job)
        return job

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return newest persisted jobs without exposing log files."""
        self._recover_interrupted()
        self.directory.mkdir(parents=True, exist_ok=True)
        paths = sorted(
            self.directory.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        history: list[dict[str, Any]] = []
        for path in paths:
            try:
                history.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
            if len(history) >= max(1, min(limit, 100)):
                break
        return history

    def _execute(self, job_id: str, runner: JobRunner) -> None:
        self._update(
            job_id,
            status="RUNNING",
            progress_pct=1,
            phase="Starting",
            detail="Job started",
            started_at=_utc_now(),
        )

        def report(progress_pct: int, phase: str, detail: str) -> None:
            self._update(
                job_id,
                progress_pct=max(1, min(int(progress_pct), 99)),
                phase=phase,
                detail=detail,
            )

        try:
            result = runner(report) or {}
            terminal_status = result.pop("job_status", "COMPLETED")
            terminal_detail = result.pop(
                "job_detail",
                "Job completed successfully",
            )
            if terminal_status not in {"COMPLETED", "FAILED", "NOT_EVALUABLE"}:
                raise ValueError(f"Unsupported terminal job status: {terminal_status}")
            self._update(
                job_id,
                status=terminal_status,
                progress_pct=100,
                phase=terminal_status.replace("_", " ").title(),
                detail=terminal_detail,
                completed_at=_utc_now(),
                result=result,
            )
        except Exception as error:  # noqa: BLE001 - persist safe failure state
            self._update(
                job_id,
                status="FAILED",
                phase="Failed",
                detail=str(error),
                completed_at=_utc_now(),
                error=f"{type(error).__name__}: {error}",
            )

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(changes)
            self._write(job)

    def _write(self, job: dict[str, Any]) -> None:
        _atomic_json(self.directory / f"{job['job_id']}.json", job)

    def _recover_interrupted(self) -> None:
        """Close stale status files left by a stopped application process."""
        self.directory.mkdir(parents=True, exist_ok=True)
        live_ids = {
            job_id for job_id, thread in self._threads.items() if thread.is_alive()
        }
        for path in self.directory.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                job.get("job_id") not in live_ids
                and job.get("status") in {"PENDING", "RUNNING"}
            ):
                job.update(
                    {
                        "status": "INTERRUPTED",
                        "completed_at": _utc_now(),
                        "detail": "The application stopped before this job completed",
                    }
                )
                if job.get("job_id") in self._jobs:
                    self._jobs[job["job_id"]] = job
                _atomic_json(path, job)


GLOBAL_JOBS = JobRegistry()
