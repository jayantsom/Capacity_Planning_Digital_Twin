"""
Database connection utilities.
Single source of truth for SQLite and DuckDB connections.
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager

import duckdb
import yaml

from src.utils.logger import logger


def load_config(config_path: str = "config/settings.yaml") -> dict:
    """Load project configuration."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_sqlite_path(db_name: str, config: dict) -> Path:
    """Resolve full path for a SQLite database file."""
    raw_dir = Path(config["paths"]["raw_sqlite"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir / db_name


@contextmanager
def sqlite_connection(db_path: Path):
    """Context manager for SQLite connections."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        logger.debug(f"SQLite connection opened: {db_path}")
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"SQLite error on {db_path}: {e}")
        raise
    finally:
        conn.close()
        logger.debug(f"SQLite connection closed: {db_path}")


def get_duckdb_connection(config: dict) -> duckdb.DuckDBPyConnection:
    """Get DuckDB analytics connection."""
    db_path = Path(config["paths"]["data_root"]) / config["databases"]["analytics"]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"DuckDB connection: {db_path}")
    return duckdb.connect(str(db_path))