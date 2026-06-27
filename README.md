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

## Verifying Database Schemas and Row Counts

To print a beautifully formatted table verifying that all raw SQLite files exist and contain their expected target tables, schemas, and records, run the snippet below for your operating system from the project root:

### For Windows (PowerShell)
```powershell
@'
import sqlite3
from pathlib import Path

dbs = [
    ('data/raw/sqlite/raw_reference_data.db',    ['site_master','test_type_master','equipment_master']),
    ('data/raw/sqlite/raw_product_master.db',    ['product_master']),
    ('data/raw/sqlite/raw_demand_forecast.db',   ['demand_forecast']),
    ('data/raw/sqlite/raw_target_test_time.db',  ['target_test_time']),
    ('data/raw/sqlite/raw_target_yield.db',      ['target_yield']),
    ('data/raw/sqlite/raw_site_equip_inv.db',    ['site_equipment_inventory']),
    ('data/raw/sqlite/raw_site_soft.db',         ['site_soft']),
    ('data/raw/sqlite/raw_mi_execution.db',      ['mi_execution']),
    ('data/raw/sqlite/raw_mi_test_param.db',     ['mi_test_param']),
    ('data/raw/sqlite/raw_mi_logs.db',           ['mi_logs']),
]
print(f'{"Database":<35} {"Table":<30} {"Rows":>12} {"Columns":>8}')
print('-' * 90)
for db_path, tables in dbs:
    p = Path(db_path)
    if not p.exists():
        print(f'MISSING: {db_path}')
        continue
    conn = sqlite3.connect(p)
    for t in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        cols  = conn.execute(f"PRAGMA table_info({t})").fetchall()
        print(f'{p.name:<35} {t:<30} {count:>12,} {len(cols):>8}')
    conn.close()
'@ | uv run python -
```
