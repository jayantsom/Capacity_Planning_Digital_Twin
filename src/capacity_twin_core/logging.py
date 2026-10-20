"""
Centralized logging configuration using loguru.
Import this in every module instead of using print().
"""

import os
import sys
from pathlib import Path

from loguru import logger


def _write_console(message: object) -> None:
    """Write UTF-8 logs safely even when Windows uses a legacy code page."""
    text = str(message)
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8", errors="replace"))
        buffer.flush()
        return
    sys.stdout.write(text)
    sys.stdout.flush()


def _default_log_dir() -> Path:
    """Resolve logs outside the repository."""
    runtime_home = os.environ.get("CAPACITY_TWIN_HOME")
    if runtime_home:
        return Path(runtime_home).expanduser() / "logs"
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "CapacityPlanningDigitalTwin" / "logs"
    return Path.home() / ".capacity_planning_digital_twin" / "logs"


def setup_logger(log_dir: str | Path | None = None, level: str = "INFO") -> None:
    """Configure loguru logger with file and console handlers."""
    log_path = Path(log_dir) if log_dir is not None else _default_log_dir()
    log_path.mkdir(parents=True, exist_ok=True)

    # Remove default handler
    logger.remove()

    # Console handler — colored, human-readable
    logger.add(
        _write_console,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
               "<level>{message}</level>",
        colorize=True,
    )

    # File handler — full detail, rotating
    logger.add(
        log_path / "pipeline_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
               "{name}:{line} | {message}",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
    )


# Initialize on import
setup_logger()

__all__ = ["logger"]