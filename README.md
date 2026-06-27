## Verification

To verify that your environment is correctly configured and all required dependencies are installed, 
run the verification script based on your operating system:

### For Windows (PowerShell)
```powershell
@'
import duckdb
import pyspark
import pandas
import numpy
from src.utils.logger import logger
from src.utils.db_utils import load_config

try:
    config = load_config()
    logger.info("Config loaded successfully")
    logger.info(f"Project: {config['project']['name']}")
    logger.info(f"DuckDB version: {duckdb.__version__}")
    logger.info(f"PySpark version: {pyspark.__version__}")
    logger.info(f"Pandas version: {pandas.__version__}")
    print("All systems ready.")
except Exception as e:
    print(f"Verification failed: {e}")
'@ | uv run python -
```

-----------------------------------------------------------------------------

## Inspecting SQLite Databases (Table Schemas & Row Counts)

To verify the presence of all raw SQLite databases and quickly inspect their table shapes (row and column counts), run the appropriate snippet below from the project root:

### For Windows (PowerShell)
```powershell
@'
import sqlite3
from pathlib import Path

dbs = [
    'data/raw/sqlite/raw_reference_data.db',
    'data/raw/sqlite/raw_product_master.db',
    'data/raw/sqlite/raw_demand_forecast.db',
    'data/raw/sqlite/raw_target_test_time.db',
    'data/raw/sqlite/raw_target_yield.db',
    'data/raw/sqlite/raw_site_equip_inv.db',
    'data/raw/sqlite/raw_site_soft.db',
]
for db in dbs:
    p = Path(db)
    if p.exists():
        conn = sqlite3.connect(p)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for t in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0]
            cols  = conn.execute(f"PRAGMA table_info({t[0]})").fetchall()
            print(f'{p.name} | {t[0]}: {count:,} rows | {len(cols)} columns')
        conn.close()
    else:
        print(f'MISSING: {db}')
'@ | uv run python -
```
