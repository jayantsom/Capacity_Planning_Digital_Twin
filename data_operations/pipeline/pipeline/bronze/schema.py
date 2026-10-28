"""
Bronze layer schema definitions.
Defines which columns are natural keys, which metadata to add,
and which validation rules apply per table.
"""

from dataclasses import dataclass, field


@dataclass
class BronzeTableConfig:
    source_db: str  # SQLite filename key from config
    source_table: str  # Table name in SQLite
    bronze_table: str  # Target table name in DuckDB
    natural_keys: list[str]  # Columns that form the natural PK
    is_planning: bool  # Add planning version/forecast metadata columns?
    is_machine: bool  # Machine tables: add data_type=ACTUAL only
    yield_columns: list[str] = field(default_factory=list)
    qty_columns: list[str] = field(default_factory=list)
    date_columns: list[str] = field(default_factory=list)
    partition_col: str = ""  # Partition column (empty = no partition)


BRONZE_CONFIGS = [
    # ── Reference tables ──────────────────────────────────────────────────
    BronzeTableConfig(
        source_db="site",
        source_table="site_master",
        bronze_table="brnz_ref_site",
        natural_keys=["site_code"],
        is_planning=False,
        is_machine=False,
    ),
    BronzeTableConfig(
        source_db="test",
        source_table="test_type_master",
        bronze_table="brnz_ref_test_type",
        natural_keys=["test_type"],
        is_planning=False,
        is_machine=False,
    ),
    BronzeTableConfig(
        source_db="machine",
        source_table="equipment_master",
        bronze_table="brnz_ref_equipment",
        natural_keys=["equipment_id"],
        is_planning=False,
        is_machine=False,
    ),
    # ── Master tables ─────────────────────────────────────────────────────
    BronzeTableConfig(
        source_db="product",
        source_table="product_master",
        bronze_table="brnz_prod_master",
        natural_keys=["product_number"],
        is_planning=False,
        is_machine=False,
    ),
    BronzeTableConfig(
        source_db="product",
        source_table="manufacturer_master",
        bronze_table="brnz_manufacturer_master",
        natural_keys=["manufacturer"],
        is_planning=False,
        is_machine=False,
    ),
    BronzeTableConfig(
        source_db="product",
        source_table="product_bom",
        bronze_table="brnz_product_bom",
        natural_keys=["bom_id"],
        is_planning=False,
        is_machine=False,
        qty_columns=["quantity_per_parent"],
    ),
    BronzeTableConfig(
        source_db="product",
        source_table="product_route",
        bronze_table="brnz_product_route",
        natural_keys=["route_id"],
        is_planning=False,
        is_machine=False,
    ),
    BronzeTableConfig(
        source_db="product",
        source_table="route_step",
        bronze_table="brnz_route_step",
        natural_keys=["route_step_id"],
        is_planning=False,
        is_machine=False,
    ),
    BronzeTableConfig(
        source_db="product",
        source_table="site_product_source",
        bronze_table="brnz_site_product_source",
        natural_keys=["source_id"],
        is_planning=False,
        is_machine=False,
    ),
    # ── Planning tables (have planning version metadata) ──────────────────────────
    BronzeTableConfig(
        source_db="demand",
        source_table="demand_requirement",
        bronze_table="brnz_demand_requirement",
        natural_keys=["demand_id"],
        is_planning=True,
        is_machine=False,
        qty_columns=[
            "quantity",
            "independent_quantity",
            "dependent_quantity",
            "total_requirement",
        ],
        partition_col="plan_as_of_date",
    ),
    BronzeTableConfig(
        source_db="test",
        source_table="target_test_time",
        bronze_table="brnz_tgt_test_time",
        natural_keys=["site", "product_number", "test_type", "planning_version_id"],
        is_planning=True,
        is_machine=False,
        partition_col="plan_as_of_date",
    ),
    BronzeTableConfig(
        source_db="yield",
        source_table="target_yield",
        bronze_table="brnz_tgt_yield",
        natural_keys=["site", "product_number", "test_type", "planning_version_id"],
        is_planning=True,
        is_machine=False,
        partition_col="plan_as_of_date",
    ),
    BronzeTableConfig(
        source_db="machine",
        source_table="site_equipment_inventory",
        bronze_table="brnz_site_equip_inv",
        natural_keys=["site", "test_equipment_id"],
        is_planning=False,
        is_machine=False,
        qty_columns=[],  # Monthly qty cols validated separately
    ),
    BronzeTableConfig(
        source_db="site",
        source_table="site_soft",
        bronze_table="brnz_site_soft",
        natural_keys=["site"],
        is_planning=False,
        is_machine=False,
    ),
    # ── Execution tables (Machine — always ACTUAL) ─────────────────────────────
    BronzeTableConfig(
        source_db="execution",
        source_table="machine_execution",
        bronze_table="brnz_machine_execution",
        natural_keys=[
            "site_code",
            "factory_code",
            "product_number",
            "test_category_id",
            "execution_date",
        ],
        is_planning=False,
        is_machine=True,
        yield_columns=["yield_avg", "final_test_yield_avg"],
        qty_columns=["passed_qty", "failed_qty", "total_qty"],
        date_columns=["execution_date"],
        partition_col="month_key",
    ),
    BronzeTableConfig(
        source_db="test",
        source_table="machine_test_param",
        bronze_table="brnz_machine_test_param",
        natural_keys=[
            "site_code",
            "factory_code",
            "product_number",
            "test_category_id",
            "execution_date",
        ],
        is_planning=False,
        is_machine=True,
        yield_columns=["first_pass_yield"],
        qty_columns=["first_pass_qty", "first_fail_qty", "total_qty"],
        date_columns=["execution_date"],
        partition_col="month_key",
    ),
    BronzeTableConfig(
        source_db="machine",
        source_table="machine_logs",
        bronze_table="brnz_machine_logs",
        natural_keys=[
            "site_code",
            "factory_code",
            "product_number",
            "test_category_id",
            "error_code",
            "log_ts",
        ],
        is_planning=False,
        is_machine=True,
        date_columns=["execution_date"],
        partition_col="month_key",
    ),
    # ── Equipment cost reference ────────────────────────────────────────────
    BronzeTableConfig(
        source_db="machine",
        source_table="equipment_cost_reference",
        bronze_table="brnz_equipment_cost_reference",
        natural_keys=["equipment_cost_reference_id"],
        is_planning=False,
        is_machine=False,
        qty_columns=[
            "purchase_cost_usd",
            "annual_maintenance_cost_usd",
            "installation_cost_usd",
            "lead_time_days",
        ],
        date_columns=["effective_start_date", "effective_end_date"],
    ),
]

# Quick lookup by bronze table name
BRONZE_CONFIG_MAP = {c.bronze_table: c for c in BRONZE_CONFIGS}
