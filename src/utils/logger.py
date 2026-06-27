"""
Centralized logging configuration using loguru.
Import this in every module instead of using print().
"""

import sys
from pathlib import Path
from loguru import logger


def setup_logger(log_dir: str = "logs", level: str = "INFO") -> None:
    """Configure loguru logger with file and console handlers."""
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    # Remove default handler
    logger.remove()

    # Console handler — colored, human-readable
    logger.add(
        sys.stdout,
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