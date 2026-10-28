"""Documentation catalog, API, and safe frontend contracts."""

import re
from importlib import import_module
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from capacity_twin_core.applications import enabled_applications
from data_operations.backend.architecture import ML_LINEAGE
from data_operations.pipeline.pipeline.bronze.schema import BRONZE_CONFIGS
from data_operations.pipeline.pipeline.gold.serving_views import SERVING_VIEWS
from documentation.backend.main import PROJECT_ROOT, _catalog, router

documentation_app = FastAPI()
documentation_app.include_router(router)
client = TestClient(documentation_app)
FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_catalog_has_one_owner_per_slug_and_path() -> None:
    groups, pages = _catalog()
    listed = [page for group in groups for page in group["pages"]]
    assert len(listed) == len(pages)
    assert len({page["path"] for page in listed}) == len(listed)
    assert all((PROJECT_ROOT / page["path"]).is_file() for page in listed)


def test_page_api_reads_the_markdown_source() -> None:
    response = client.get("/documentation/api/pages/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["markdown"] == (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")


def test_frontend_uses_safe_dom_rendering() -> None:
    script = (FRONTEND / "documentation.js").read_text(encoding="utf-8")
    assert ".textContent" in script
    assert "innerHTML" not in script
    assert "eval(" not in script
    assert "normalizedHeading(heading[2]) === normalizedHeading(pageTitle)" in script
    assert "renderMarkdown(payload.markdown, payload.title)" in script


def test_owned_docs_use_ml_casing_and_no_em_dash() -> None:
    _, pages = _catalog()
    for item in pages.values():
        text = (PROJECT_ROOT / item["path"]).read_text(encoding="utf-8")
        assert "\u2014" not in text, item["path"]
        assert "Ml " not in text, item["path"]


def test_documented_applications_match_the_enabled_registry() -> None:
    architecture = (PROJECT_ROOT / "docs/architecture/system-architecture.md").read_text(
        encoding="utf-8"
    )
    applications_section = architecture.split("## Applications", 1)[1].split("## UI", 1)[0]
    documented = re.findall(
        r"^\| `([^`]+)` \| ([^|]+) \|$", applications_section, re.MULTILINE
    )
    expected = [
        (app.route, "Capacity Home" if app.app_id == "home" else app.title)
        for app in enabled_applications()
    ]
    assert documented == expected


def test_documented_layer_counts_match_pipeline_contracts() -> None:
    silver_tables = import_module("data_operations.pipeline.steps.2_silver").REQUIRED_TABLES
    gold_tables = import_module("data_operations.pipeline.steps.3_gold").REQUIRED_TABLES
    counts = {
        "Raw databases": len({config.source_db for config in BRONZE_CONFIGS}),
        "Raw tables": len(BRONZE_CONFIGS),
        "Bronze": len(BRONZE_CONFIGS),
        "Silver": len(silver_tables),
        "Gold": len(gold_tables),
        "Serving": len(SERVING_VIEWS),
        "ML": len(ML_LINEAGE),
    }
    assert counts == {
        "Raw databases": 7,
        "Raw tables": 18,
        "Bronze": 18,
        "Silver": 22,
        "Gold": 14,
        "Serving": 19,
        "ML": 12,
    }
    overview = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    for expected_text in (
        "7 Raw SQLite databases with 18 source tables",
        "Bronze DuckDB database with 18 tables",
        "Silver DuckDB database with 22 tables",
        "Gold DuckDB database with 14 tables",
        "Serving DuckDB database with 19 tables",
        "ML DuckDB database with 12 tables",
    ):
        assert expected_text in overview


def test_owned_documentation_excludes_retired_contracts() -> None:
    _, pages = _catalog()
    owned_paths = {PROJECT_ROOT / item["path"] for item in pages.values()}
    owned_paths.add(PROJECT_ROOT / "documentation/config.yaml")
    fragments = {
        "retired app id": [
            "scenario" + "-planning",
            "demand" + "-supply-planning",
            "n" + "pi-ramp-planning",
            "operations" + "-flow",
            "scenario" + "_planning",
            "demand" + "_supply_planning",
            "n" + "pi_ramp_planning",
            "operations" + "_flow",
        ],
        "retired database": ["raw_" + "inventory.db", "raw_" + "n" + "pi.db"],
        "retired table family": [
            "gold_" + "so" + "p_",
            "srv_" + "so" + "p_",
            "gold_" + "n" + "pi_",
            "srv_" + "n" + "pi_",
            "gold_" + "operations_",
            "srv_" + "operations_",
            "gold_" + "scenario_inputs",
            "srv_" + "scenario_inputs",
        ],
        "retired concept": ["s&" + "op"],
    }
    concept_pattern = re.compile(r"\b" + "n" + r"pi\b", re.IGNORECASE)
    for path in sorted(owned_paths):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for label, values in fragments.items():
            for value in values:
                assert value.lower() not in lowered, f"{path}: {label}: {value}"
        assert concept_pattern.search(text) is None, f"{path}: retired concept"
