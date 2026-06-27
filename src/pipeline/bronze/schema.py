"""
Bronze layer schema definitions.
Defines which columns are natural keys, which metadata to add,
and which validation rules apply per table.
"""

from dataclasses import dataclass, field


@dataclass
class BronzeTableConfig:
    source_db: str           # SQLite filename key from config
    source_table: str        # Table name in SQLite
    bronze_table: str        # Target table name in DuckDB
    natural_keys: list[str]  # Columns that form the natural PK
    is_planning: bool        # Add snapshot/forecast metadata columns?
    is_mi: bool              # MI tables: add data_type=ACTUAL only
    yield_columns: list[str] = field(default_factory=list)
    qty_columns: list[str]   = field(default_factory=list)
    date_columns: list[str]  = field(default_factory=list)
    partition_col: str = ""  # Partition column (empty = no partition)


BRONZE_CONFIGS = [
    # ── Reference tables ──────────────────────────────────────────────────
    BronzeTableConfig(
        source_db="reference_data",
        source_table="site_master",
        bronze_table="brnz_ref_site",
        natural_keys=["site_code"],
        is_planning=False, is_mi=False,
    ),
    BronzeTableConfig(
        source_db="reference_data",
        source_table="test_type_master",
        bronze_table="brnz_ref_test_type",
        natural_keys=["test_type"],
        is_planning=False, is_mi=False,
    ),
    BronzeTableConfig(
        source_db="reference_data",
        source_table="equipment_master",
        bronze_table="brnz_ref_equipment",
        natural_keys=["equipment_id"],
        is_planning=False, is_mi=False,
    ),

    # ── Master tables ─────────────────────────────────────────────────────
    BronzeTableConfig(
        source_db="product_master",
        source_table="product_master",
        bronze_table="brnz_prod_master",
        natural_keys=["product_number"],
        is_planning=False, is_mi=False,
    ),

    # ── Planning tables (have snapshot metadata) ──────────────────────────
    BronzeTableConfig(
        source_db="demand_forecast",
        source_table="demand_forecast",
        bronze_table="brnz_dmnd_forecast",
        natural_keys=["site", "product_number", "snapshot_id"],
        is_planning=True, is_mi=False,
        qty_columns=[],  # Horizontal month cols validated separately
        partition_col="snapshot_date",
    ),
    BronzeTableConfig(
        source_db="target_test_time",
        source_table="target_test_time",
        bronze_table="brnz_tgt_test_time",
        natural_keys=["site", "product_number", "test_type", "snapshot_id"],
        is_planning=True, is_mi=False,
        partition_col="snapshot_date",
    ),
    BronzeTableConfig(
        source_db="target_yield",
        source_table="target_yield",
        bronze_table="brnz_tgt_yield",
        natural_keys=["site", "product_number", "test_type", "snapshot_id"],
        is_planning=True, is_mi=False,
        partition_col="snapshot_date",
    ),
    BronzeTableConfig(
        source_db="site_equipment_inventory",
        source_table="site_equipment_inventory",
        bronze_table="brnz_site_equip_inv",
        natural_keys=["site", "test_equipment_id"],
        is_planning=False, is_mi=False,
        qty_columns=[],   # Monthly qty cols validated separately
    ),
    BronzeTableConfig(
        source_db="site_soft",
        source_table="site_soft",
        bronze_table="brnz_site_soft",
        natural_keys=["site"],
        is_planning=False, is_mi=False,
    ),

    # ── Execution tables (MI — always ACTUAL) ─────────────────────────────
    BronzeTableConfig(
        source_db="manufacturing_intelligence",
        source_table="mi_execution",
        bronze_table="brnz_mi_execution",
        natural_keys=["factory_code", "product_number",
                      "test_category_id", "execution_date"],
        is_planning=False, is_mi=True,
        yield_columns=["yield_avg", "final_test_yield_avg"],
        qty_columns=["passed_qty", "failed_qty", "total_qty"],
        date_columns=["execution_date"],
        partition_col="month_key",
    ),
    BronzeTableConfig(
        source_db="test_x_parameter",
        source_table="mi_test_param",
        bronze_table="brnz_mi_test_param",
        natural_keys=["factory_code", "product_number",
                      "test_category_id", "execution_date"],
        is_planning=False, is_mi=True,
        yield_columns=["first_pass_yield"],
        qty_columns=["first_pass_qty", "first_fail_qty", "total_qty"],
        date_columns=["execution_date"],
        partition_col="month_key",
    ),
    BronzeTableConfig(
        source_db="mi_logs",
        source_table="mi_logs",
        bronze_table="brnz_mi_logs",
        natural_keys=["product_number", "test_category_id",
                      "error_code", "execution_date"],
        is_planning=False, is_mi=True,
        date_columns=["execution_date"],
        partition_col="month_key",
    ),
]

# Quick lookup by bronze table name
BRONZE_CONFIG_MAP = {c.bronze_table: c for c in BRONZE_CONFIGS}